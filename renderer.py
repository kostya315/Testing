import os
import sys
import time
import struct
import mmap
import win32event
import win32api
import pywintypes
import numpy as np
import cv2
import queue
from PyQt5.QtCore import QObject, pyqtSlot, QTimer, QPointF, QPropertyAnimation, QEasingCurve, Qt, QSize
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsProxyWidget, QLabel
from PyQt5.QtGui import QImage, QPainter, QMovie

import config_manager

# --- КОНФИГУРАЦИЯ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_ASSETS_FOLDER = os.path.join(SCRIPT_DIR, "reactive_avatar")
STATUS_TO_FILENAME_MAP = {
    "Говорит": "Speaking",
    "Молчит": "Inactive",
    "Микрофон выключен (muted)": "Muted",
    "Полностью заглушен (deafened)": "Deafened",
    "Картинка загружается (или не определена)": "Inactive",
    "Ошибка": "Inactive",
    "Элемент статуса голоса не найден.": "Inactive"
}
BACKGROUND_IMAGE_BASENAME = "BG"

# --- КОНФИГУРАЦИЯ ОБЩЕЙ ПАМЯТИ ---
SHARED_MEM_NAME = "LunasVirtualCamSharedMemory"
NEW_FRAME_EVENT_NAME = "LunasVirtualCamNewFrameEvent"
MAX_BUFFER_SIZE = 1920 * 1080 * 3  # RGB24
SHARED_BUFFER_HEADER_FORMAT = "<IIIIII"
SHARED_BUFFER_HEADER_SIZE = struct.calcsize(SHARED_BUFFER_HEADER_FORMAT)
TOTAL_SHARED_MEM_SIZE = SHARED_BUFFER_HEADER_SIZE + MAX_BUFFER_SIZE


class Renderer(QObject):
    """
    Управляет рендерингом сцены с аватарами и отправкой кадров в общую память.
    Работает в основном потоке GUI.
    """

    def __init__(self, display_queue, parent=None):
        super().__init__(parent)
        self.display_queue = display_queue
        self.config = {}
        self.cam_width = 1920
        self.cam_height = 1080
        self.cam_fps = 60

        self.avatar_proxies = {}
        self.bg_proxy = None
        self.bg_movie = None

        self.active_proxy = None

        self._shared_memory_map = None
        self._shared_memory_buffer = None
        self._new_frame_event = None
        self.is_running = False

        self._last_known_status = "Молчит"

        self._initialize_scene()
        self._initialize_shared_memory()

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._render_and_send_frame)

    def _initialize_scene(self):
        """Инициализирует QGraphicsScene."""
        print("Инициализация сцены рендерера...")
        self.scene = QGraphicsScene()
        self.load_config_and_assets()
        self.active_proxy = self.avatar_proxies.get("Молчит")
        if self.active_proxy:
            self.active_proxy.setOpacity(1.0)
            self.active_proxy.show()

    def load_config_and_assets(self):
        """Загружает конфигурацию и (пере)загружает все графические ресурсы."""
        self.config = config_manager.load_config()
        self.cam_fps = int(self.config.get('CAM_FPS', 60))

        bg_path_gif = os.path.join(AVATAR_ASSETS_FOLDER, f"{BACKGROUND_IMAGE_BASENAME}.gif")
        bg_path_png = os.path.join(AVATAR_ASSETS_FOLDER, f"{BACKGROUND_IMAGE_BASENAME}.png")
        bg_path = bg_path_gif if os.path.exists(bg_path_gif) else bg_path_png

        if os.path.exists(bg_path):
            bg_img = QImage(bg_path)
            self.cam_width = bg_img.width()
            self.cam_height = bg_img.height()
        else:
            self.cam_width = 1920
            self.cam_height = 1080
            print("ПРЕДУПРЕЖДЕНИЕ: Файл фона не найден, используется разрешение по умолчанию 1920x1080.")

        self.scene.setSceneRect(0, 0, self.cam_width, self.cam_height)
        self.scene.clear()
        self.avatar_proxies = {}

        if os.path.exists(bg_path):
            self.bg_movie = QMovie(bg_path)
            bg_label = QLabel()
            bg_label.setMovie(self.bg_movie)
            self.bg_proxy = self.scene.addWidget(bg_label)
            self.bg_proxy.setZValue(0)
            self.bg_movie.start()

        for status, filename in STATUS_TO_FILENAME_MAP.items():
            gif_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{filename}.gif")
            png_path = os.path.join(AVATAR_ASSETS_FOLDER, f"{filename}.png")
            file_path = gif_path if os.path.exists(gif_path) else png_path

            if os.path.exists(file_path):
                movie = QMovie(file_path)
                avatar_label = QLabel()
                avatar_label.setMovie(movie)

                avatar_size = movie.currentImage().size()
                proxy = self.scene.addWidget(avatar_label)
                x_offset = (self.cam_width - avatar_size.width()) / 2
                y_offset = self.cam_height - avatar_size.height()
                proxy.setPos(x_offset, y_offset)

                proxy.setZValue(1)
                proxy.setOpacity(0.0)
                proxy.hide()
                self.avatar_proxies[status] = proxy
                movie.start()

    def _initialize_shared_memory(self):
        """Инициализирует общую память и событие Win32."""
        try:
            self._shared_memory_map = mmap.mmap(-1, TOTAL_SHARED_MEM_SIZE, tagname=SHARED_MEM_NAME)
        except Exception:
            self._shared_memory_map = mmap.mmap(-1, TOTAL_SHARED_MEM_SIZE, tagname=SHARED_MEM_NAME,
                                                access=mmap.ACCESS_WRITE)
        self._shared_memory_buffer = memoryview(self._shared_memory_map)

        try:
            self._new_frame_event = win32event.OpenEvent(win32event.EVENT_ALL_ACCESS, False, NEW_FRAME_EVENT_NAME)
        except pywintypes.error:
            self._new_frame_event = win32event.CreateEvent(None, False, False, NEW_FRAME_EVENT_NAME)

    def start_rendering(self):
        if self.is_running: return
        self.is_running = True
        self.render_timer.start(1000 // self.cam_fps if self.cam_fps > 0 else 33)

    def stop_rendering(self):
        if not self.is_running: return
        self.is_running = False
        self.render_timer.stop()

    def cleanup(self):
        self.stop_rendering()
        if self._shared_memory_map: self._shared_memory_map.close()
        if self._new_frame_event: win32api.CloseHandle(self._new_frame_event)

    @pyqtSlot(str, str)
    def on_status_changed(self, status_message: str, debug_message: str):
        if status_message == self._last_known_status: return

        print(f"Renderer: Статус изменился на '{status_message}'. {debug_message}")

        old_proxy = self.active_proxy
        new_proxy = self.avatar_proxies.get(status_message, self.avatar_proxies.get("Молчит"))

        if old_proxy is new_proxy: return

        self._last_known_status = status_message
        self.active_proxy = new_proxy

        is_instant = self.config.get('INSTANT_TALK_TRANSITION',
                                     'True').lower() == 'true' and status_message == "Говорит"
        fade_duration = int(self.config.get('CROSS_FADE_DURATION_MS', 200))

        if new_proxy:
            new_proxy.show()
            fade_in = QPropertyAnimation(new_proxy, b"opacity")
            fade_in.setDuration(fade_duration if not is_instant else 0)
            fade_in.setStartValue(new_proxy.opacity())
            fade_in.setEndValue(1.0)
            fade_in.start(QPropertyAnimation.DeleteWhenStopped)

        if old_proxy:
            fade_out = QPropertyAnimation(old_proxy, b"opacity")
            fade_out.setDuration(fade_duration)
            fade_out.setStartValue(old_proxy.opacity())
            fade_out.setEndValue(0.0)
            fade_out.finished.connect(old_proxy.hide)
            fade_out.start(QPropertyAnimation.DeleteWhenStopped)

        if self.config.get('BOUNCING_ENABLED', 'True').lower() == 'true' and status_message == "Говорит" and new_proxy:
            bounce_animation = QPropertyAnimation(new_proxy, b"pos")
            bounce_animation.setDuration(150)
            start_pos = new_proxy.pos()
            bounce_animation.setStartValue(start_pos)
            bounce_animation.setKeyValueAt(0.5, QPointF(start_pos.x(), start_pos.y() - 10))
            bounce_animation.setEndValue(start_pos)
            bounce_animation.setEasingCurve(QEasingCurve.OutQuad)
            bounce_animation.start(QPropertyAnimation.DeleteWhenStopped)

    def _render_and_send_frame(self):
        if not self.is_running or not self._shared_memory_buffer: return

        image = QImage(self.cam_width, self.cam_height, QImage.Format_RGB888)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        self.scene.render(painter)
        painter.end()

        ptr = image.bits()
        ptr.setsize(image.sizeInBytes())
        frame_data_bytes = ptr.asstring()

        try:
            header = struct.pack(SHARED_BUFFER_HEADER_FORMAT, self.cam_width, self.cam_height, self.cam_fps, 0,
                                 len(frame_data_bytes), 1)
            self._shared_memory_buffer[:SHARED_BUFFER_HEADER_SIZE] = header
            self._shared_memory_buffer[
            SHARED_BUFFER_HEADER_SIZE:SHARED_BUFFER_HEADER_SIZE + len(frame_data_bytes)] = frame_data_bytes
            win32event.SetEvent(self._new_frame_event)
        except Exception as e:
            print(f"Ошибка записи в общую память: {e}")
            self.stop_rendering()
            return

        try:
            # Преобразуем для предпросмотра, ИСПРАВЛЯЯ ПОРЯДОК КАНАЛОВ
            # QImage.Format_RGB888 дает байты в порядке R, G, B.
            # OpenCV np.frombuffer и reshape создаст массив с каналами в том же порядке (RGB).
            # Для отображения через QPixmap, который тоже ожидает RGB, конвертация не нужна.
            # Но если бы мы использовали cv2.imshow, потребовался бы cv2.cvtColor(frame, cv2.COLOR_RGB2BGR).
            # Для QImage(data, ... Format_RGB888) данные уже должны быть RGB.
            frame_for_gui = np.frombuffer(frame_data_bytes, dtype=np.uint8).reshape(
                (self.cam_height, self.cam_width, 3))

            while not self.display_queue.empty():
                self.display_queue.get_nowait()
            self.display_queue.put_nowait(frame_for_gui)
        except queue.Full:
            pass
        except Exception as e:
            print(f"Ошибка отправки кадра в GUI: {e}")
