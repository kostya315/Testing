import os
import sys
import time
import cv2
import numpy as np
from PIL import Image
from io import BytesIO
import threading
import asyncio
import queue

# Импортируем PyQt5
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QSystemTrayIcon, QMenu, QAction, QHBoxLayout, \
    QPushButton, QSizePolicy, QDesktopWidget, QGraphicsOpacityEffect, QLineEdit, QMessageBox
from PyQt5.QtGui import QPixmap, QImage, QIcon, QPalette, QBrush, QColor, QScreen, QCursor
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint, QPropertyAnimation, QEasingCurve, QSize, QSettings

# Импортируем virtual_camera как модуль, чтобы получить доступ к display_queue и CAM_WIDTH/HEIGHT
import virtual_camera
import reactive_monitor # Предполагается, что reactive_monitor существует и вызывает virtual_camera.voice_status_callback
import utils # Предполагается, что utils существует
import logging_manager # Добавляем импорт logging_manager

# Определяем директорию скрипта для путей к файлам
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- КОНФИГУРАЦИЯ ОКНА ---
WINDOW_TITLE = "Виртуальная Камера Reactive"
ICON_PATH = os.path.join(SCRIPT_DIR, "app_icon.png")  # Путь к файлу иконки приложения и трея


# --- Заглушки изображений ---
def create_placeholder_images_for_gui():
    """Создает заглушки изображений для GUI и трея, если они отсутствуют.
       Использует Pillow для сохранения PNG, чтобы избежать ошибок OpenCV.
    """
    print("Проверка наличия изображений-заглушек в 'reactive_avatar' и 'app_icon.png'...")
    os.makedirs(virtual_camera.AVATAR_ASSETS_FOLDER, exist_ok=True)

    # Вспомогательная функция для сохранения NumPy массива в PNG с Pillow
    def save_np_array_as_png(np_array, path):
        img_pil = Image.fromarray(np_array)
        img_pil.save(path, format="PNG")

    # Создаем app_icon.png
    if not os.path.exists(ICON_PATH):
        print(f"  Создаю заглушку '{os.path.basename(ICON_PATH)}'.")
        icon_size = 64
        placeholder_icon = np.zeros((icon_size, icon_size, 4), dtype=np.uint8)
        cv2.circle(placeholder_icon, (icon_size // 2, icon_size // 2), icon_size // 2 - 5, (255, 165, 0, 255),
                   -1)  # Оранжевый круг
        cv2.putText(placeholder_icon, "VC", (icon_size // 2 - 15, icon_size // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_icon, ICON_PATH)

    # Создаем BG.png - заглушка для определения размера CAM_WIDTH/HEIGHT
    # Используем virtual_camera.BACKGROUND_IMAGE_PATH
    bg_path = os.path.join(virtual_camera.AVATAR_ASSETS_FOLDER, f"{virtual_camera.BACKGROUND_IMAGE_PATH}.png")
    if not os.path.exists(bg_path):
        print(f"  Создаю заглушку '{os.path.basename(bg_path)}'.")
        placeholder_bg = np.full((480, 640, 3), 150, dtype=np.uint8)  # Серое 640x480
        save_np_array_as_png(placeholder_bg, bg_path)

    # Создаем Speaking.png
    speaking_path = os.path.join(virtual_camera.AVATAR_ASSETS_FOLDER,
                                 f"{virtual_camera.STATUS_TO_FILENAME_MAP['Говорит']}.png")
    if not os.path.exists(speaking_path):
        print(f"  Создаю заглушку '{os.path.basename(speaking_path)}'.")
        avatar_size = 200
        placeholder_avatar = np.zeros((avatar_size, avatar_size, 4), dtype=np.uint8)
        center = (avatar_size // 2, avatar_size // 2)
        radius = avatar_size // 2 - 10
        cv2.circle(placeholder_avatar, center, radius, (0, 255, 0, 255), -1)  # Зеленый круг, альфа 255
        cv2.putText(placeholder_avatar, "Speaking", (center[0] - 60, center[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_avatar, speaking_path)

    # Создаем Inactive.png
    inactive_path = os.path.join(virtual_camera.AVATAR_ASSETS_FOLDER,
                                 f"{virtual_camera.STATUS_TO_FILENAME_MAP['Молчит']}.png")
    if not os.path.exists(inactive_path):
        print(f"  Создаю заглушку '{os.path.basename(inactive_path)}'.")
        if os.path.exists(speaking_path):
            # Загружаем Speaking.png, затемняем и сохраняем как Inactive.png
            try:
                img_bytes = open(speaking_path, 'rb').read()
                img = Image.open(BytesIO(img_bytes)).convert("RGBA")
                pixels = img.load()
                dim_factor = 1.0 - (50 / 100.0)  # 50% затемнения
                for y in range(img.height):
                    for x in range(img.width):
                        r, g, b, a = pixels[x, y]
                        pixels[x, y] = (int(r * dim_factor), int(g * dim_factor), int(b * dim_factor), a)
                output_buffer = BytesIO()
                img.save(output_buffer, format="PNG")
                with open(inactive_path, 'wb') as f:
                    f.write(output_buffer.getvalue())
            except Exception as e:
                print(f"Ошибка при создании Inactive.png из Speaking.png: {e}")
                # Fallback: Если не удалось, создаем простую серую заглушку
                placeholder_inactive = np.zeros((200, 200, 4), dtype=np.uint8)
                cv2.circle(placeholder_inactive, (100, 100), 90, (100, 100, 100, 255), -1)  # Серый круг
                cv2.putText(placeholder_inactive, "Inactive", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255),
                            2)
                save_np_array_as_png(placeholder_inactive, inactive_path)
        else:
            # Если Speaking.png тоже нет, создаем просто заглушку
            placeholder_inactive = np.zeros((200, 200, 4), dtype=np.uint8)
            cv2.circle(placeholder_inactive, (100, 100), 90, (100, 100, 100, 255), -1)  # Серый круг
            cv2.putText(placeholder_inactive, "Inactive", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
            save_np_array_as_png(placeholder_inactive, inactive_path)

    # Создаем Muted.png (Микрофон выключен) - КРАСНЫЙ (BGR для OpenCV)
    muted_path = os.path.join(virtual_camera.AVATAR_ASSETS_FOLDER,
                              f"{virtual_camera.STATUS_TO_FILENAME_MAP['Микрофон выключен (muted)']}.png")
    if not os.path.exists(muted_path):
        print(f"  Создаю заглушку '{os.path.basename(muted_path)}'.")
        placeholder_muted = np.zeros((200, 200, 4), dtype=np.uint8)
        cv2.circle(placeholder_muted, (100, 100), 90, (0, 0, 200, 255), -1)  # Ярко-красный круг (BGR)
        cv2.putText(placeholder_muted, "Muted", (60, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_muted, muted_path)

    # Создаем Deafened.png (Полностью заглушен) - СИНИЙ (BGR для OpenCV)
    deafened_path = os.path.join(virtual_camera.AVATAR_ASSETS_FOLDER,
                                 f"{virtual_camera.STATUS_TO_FILENAME_MAP['Полностью заглушен (deafened)']}.png")
    if not os.path.exists(deafened_path):
        print(f"  Создаю заглушку '{os.path.basename(deafened_path)}'.")
        placeholder_deafened = np.zeros((200, 200, 4), dtype=np.uint8)
        cv2.circle(placeholder_deafened, (100, 100), 90, (200, 0, 0, 255), -1)  # Ярко-синий круг (BGR)
        cv2.putText(placeholder_deafened, "Deafened", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_deafened, deafened_path)

    print("Проверка заглушек завершена.")


class CustomTitleBar(QWidget):
    """
    Кастомная полоса заголовка для окна.
    Обрабатывает перетаскивание окна и кнопки управления.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.start_pos = None
        self.maximized = False

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#1a1a1a"))
        self.setPalette(palette)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                font-family: Arial;
                font-size: 12px;
            }
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                padding: 5px 10px; /* Внутренние отступы */
                margin: 0px; /* Убираем внешние отступы */
                min-width: 30px;
                font-weight: bold;
                border-radius: 0px; /* Default: no rounding */
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton#closeButton:hover {
                background-color: #e81123;
            }
            QPushButton#quitButton { /* Specific style for quitButton */
                border-top-right-radius: 10px; /* Apply rounding to the top-right corner */
            }
            QPushButton#quitButton:hover {
                background-color: #e81123;
            }
        """)
        self.setFixedHeight(30)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 0, 0)
        layout.setSpacing(0)  # Убираем отступы между элементами

        self.icon_label = QLabel(self)
        if os.path.exists(ICON_PATH):
            pixmap = QPixmap(ICON_PATH).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pixmap)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(WINDOW_TITLE, self)
        layout.addWidget(self.title_label)

        layout.addStretch()

        self.minimize_button = QPushButton("—", self)
        self.minimize_button.clicked.connect(self.parent_window.showMinimized)
        self.minimize_button.setToolTip("Свернуть")
        layout.addWidget(self.minimize_button)

        self.maximize_restore_button = QPushButton("☐", self)
        self.maximize_restore_button.clicked.connect(self.toggle_maximize_restore)
        self.maximize_restore_button.setToolTip("Развернуть")
        layout.addWidget(self.maximize_restore_button)

        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("closeButton")
        self.close_button.clicked.connect(self.parent_window.close)
        self.close_button.setToolTip("Свернуть в трей")
        layout.addWidget(self.close_button)

        self.quit_button = QPushButton("⏻", self)
        self.quit_button.setObjectName("quitButton")
        self.quit_button.clicked.connect(self.parent_window.quit_app)
        self.quit_button.setToolTip("Выйти из приложения")
        layout.addWidget(self.quit_button)

    def toggle_maximize_restore(self):
        """Переключает состояние окна между максимизированным и нормальным."""
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.maximized = False
            self.maximize_restore_button.setText("☐")
            self.maximize_restore_button.setToolTip("Развернуть")
        else:
            self.parent_window.showMaximized()
            self.maximized = True
            self.maximize_restore_button.setText("🗗")
            self.maximize_restore_button.setToolTip("Восстановить")

    def mousePressEvent(self, event):
        """Начало перетаскивания окна."""
        if event.button() == Qt.LeftButton:
            self.start_pos = event.globalPos() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Перетаскивание окна."""
        if event.buttons() == Qt.LeftButton and self.start_pos is not None:
            if not self.maximized:
                self.parent_window.move(event.globalPos() - self.start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Окончание перетаскивания."""
        self.start_pos = None
        event.accept()


class AnimatedMenu(QMenu):
    """
    Кастомное QMenu, которое появляется и исчезает с анимацией прозрачности.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

        self.opacity_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.opacity_animation.setDuration(200)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutQuad)

        self.aboutToHide.connect(self._start_fade_out)

    def popup(self, pos, action=None):
        """
        Переопределяем метод popup для запуска анимации появления.
        """
        print("AnimatedMenu: popup called")
        if self.opacity_animation.state() == QPropertyAnimation.Running:
            self.opacity_animation.stop()
            print("AnimatedMenu: Stopped running animation in popup.")

        self.opacity_effect.setOpacity(0.0)

        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
            print("AnimatedMenu: Disconnected _actual_hide from finished in popup.")
        except TypeError:
            pass

        super().popup(pos, action)
        print("AnimatedMenu: super().popup called.")

        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.start()
        print("AnimatedMenu: Fade-in animation started.")

    def _start_fade_out(self):
        """
        Запускает анимацию скрытия меню.
        """
        print("AnimatedMenu: _start_fade_out called (triggered by aboutToHide)")
        if self.opacity_animation.state() == QPropertyAnimation.Running and self.opacity_animation.endValue() == 0.0:
            print("AnimatedMenu: Already fading out, skipping new fade-out animation.")
            return

        if self.opacity_animation.state() == QPropertyAnimation.Running:
            self.opacity_animation.stop()
            print("AnimatedMenu: Stopped running animation in _start_fade_out.")

        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
            print("AnimatedMenu: Disconnected _actual_hide from finished in _start_fade_out (cleanup).")
        except TypeError:
            pass

        self.opacity_animation.setStartValue(self.opacity_effect.opacity())
        self.opacity_animation.setEndValue(0.0)

        self.opacity_animation.finished.connect(self._actual_hide)
        self.opacity_animation.start()
        print("AnimatedMenu: Fade-out animation started.")

    def _actual_hide(self):
        """
        Скрывает меню после завершения анимации исчезновения.
        """
        print("AnimatedMenu: _actual_hide called (triggered by animation finished)")
        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
            print("AnimatedMenu: Disconnected _actual_hide from finished in _actual_hide.")
        except TypeError:
            pass
        self.hide()
        print("AnimatedMenu: self.hide() called.")


class CameraWindow(QWidget):
    update_image_signal = pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")

        self.setWindowOpacity(0.0)

        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
            print(f"Иконка окна успешно установлена из: {ICON_PATH}")
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Файл иконки '{ICON_PATH}' не найден. Окно будет без иконки.")

        main_window_layout = QVBoxLayout(self)
        main_window_layout.setContentsMargins(0, 0, 0, 0)
        main_window_layout.setSpacing(0)

        self.main_container_widget = QWidget(self)
        self.main_container_widget.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-radius: 12px; /* Добавляем скругление углов для главного контейнера */
            }
        """)
        main_container_layout = QVBoxLayout(self.main_container_widget)
        main_container_layout.setContentsMargins(0, 0, 0, 0)
        main_container_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        main_container_layout.addWidget(self.title_bar)

        self.content_inner_widget = QWidget(self.main_container_widget)
        content_inner_layout = QVBoxLayout(self.content_inner_widget)
        content_inner_layout.setContentsMargins(10, 10, 10, 10)
        content_inner_layout.setSpacing(0)

        self.image_label = QLabel(self.main_container_widget)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setStyleSheet("background-color: black;")
        content_inner_layout.addWidget(self.image_label)

        main_container_layout.addWidget(self.content_inner_widget)

        main_window_layout.addWidget(self.main_container_widget)

        ANIMATION_DURATION = 200

        self.size_animation = QPropertyAnimation(self, b"size")
        self.size_animation.setDuration(ANIMATION_DURATION)
        self.size_animation.setEasingCurve(QEasingCurve.OutQuad)

        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(ANIMATION_DURATION)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutQuad)

        self.pos_animation = QPropertyAnimation(self, b"pos")
        self.pos_animation.setDuration(ANIMATION_DURATION)
        self.pos_animation.setStartValue(QPoint(0,0)) # Инициализируем, так как он может быть None
        self.pos_animation.setEndValue(QPoint(0,0)) # Инициализируем, так как он может быть None
        self.pos_animation.setEasingCurve(QEasingCurve.OutQuad)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(ICON_PATH))
        self.tray_icon.activated.connect(self.tray_activated)

        self.tray_menu = AnimatedMenu(self)
        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self.show_window)
        self.tray_menu.addAction(show_action)

        self.tray_menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(quit_action)

        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: transparent;
                border-radius: 0px;
                border: none;
                font-family: Arial;
                font-size: 13px;
                color: #ffffff;
            }
            QMenu::item {
                background-color: rgba(51, 51, 51, 0.95);
                padding: 6px 15px;
                border-radius: 0px;
                margin: 0px;
            }
            QMenu::item:selected {
                background-color: #007bff;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(80, 80, 80, 0.5);
            }
        """)

        self.tray_icon.show()

        self.update_image_signal.connect(self.update_image)

        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self.check_for_new_frame)
        self.frame_timer.start(1000 // (virtual_camera.CAM_FPS if virtual_camera.CAM_FPS > 0 else 30))

        self.status = "Молчит"

        default_cam_width = 640
        default_cam_height = 480

        min_height_fixed_elements = self.title_bar.height() + \
                                    self.content_inner_widget.layout().contentsMargins().top() + \
                                    self.content_inner_widget.layout().contentsMargins().bottom()

        self.setMinimumSize(160, min_height_fixed_elements + 100)

        self._current_cv_frame = None

        # Инициализируем CustomStatusHandler
        self.status_handler = CustomStatusHandler(self._handle_status_update_on_gui_thread)
        # УДАЛЕНО: self.status_handler.console_print_signal.connect(self._print_status_to_console)
        # Эта строка удалена, так как console_print_signal больше не существует в CustomStatusHandler.

        self.settings = QSettings("ReactivePlus", "VirtualCameraReactive")
        self.load_window_state()

        # Вызов _update_demo_image_with_status_circle() только здесь, при инициализации.
        self._update_demo_image_with_status_circle()

    def calculate_target_geometry(self):
        """
        Рассчитывает целевую геометрию окна на основе CAM_WIDTH/HEIGHT
        и размеров фиксированных элементов GUI.
        Возвращает QSize для целевого размера.
        """
        current_cam_width = virtual_camera.CAM_WIDTH if virtual_camera.CAM_WIDTH > 0 else 640
        current_cam_height = virtual_camera.CAM_HEIGHT if virtual_camera.CAM_HEIGHT > 0 else 480

        self.layout().activate()
        self.main_container_widget.layout().activate()
        self.content_inner_widget.layout().activate()

        target_height_fixed_elements = self.title_bar.height() + \
                                    self.content_inner_widget.layout().contentsMargins().top() + \
                                    self.content_inner_widget.layout().contentsMargins().bottom()

        total_layout_spacing = self.main_container_widget.layout().spacing() * 2

        target_total_height = current_cam_height + target_height_fixed_elements + total_layout_spacing

        return QSize(current_cam_width, target_total_height)

    def move_to_active_screen_center(self):
        """
        Перемещает окно в центр экрана, где находится курсор мыши.
        Устанавливает геометрию без анимации.
        """
        current_screen = QApplication.screenAt(QCursor.pos())
        if current_screen is None:
            current_screen = QApplication.primaryScreen()

        screen_geo = current_screen.availableGeometry()
        screen_center_x = screen_geo.center().x()
        screen_center_y = screen_geo.center().y()

        target_size = self.calculate_target_geometry()
        target_x = screen_center_x - (target_size.width() // 2)
        target_y = screen_center_y - (target_size.height() // 2)

        self.setGeometry(target_x, target_y, target_size.width(), target_size.height())

    def load_window_state(self):
        """Загружает сохраненное положение окна и состояние из QSettings."""
        print("Загрузка состояния окна...")
        minimized_to_tray = self.settings.value("minimizedToTray", False, type=bool)
        print(f"  Minimized to tray last time: {minimized_to_tray}")

        if minimized_to_tray:
            self.hide()
            self.tray_icon.showMessage(
                "Виртуальная Камера Reactive",
                "Приложение было свернуто в трей при последнем запуске.",
                QSystemTrayIcon.Information,
                2000
            )
            return

        geometry_data = self.settings.value("geometry")
        if geometry_data:
            print("  Попытка восстановить сохраненную геометрию.")
            self.restoreGeometry(geometry_data)

            is_on_screen = False
            current_rect = self.frameGeometry()
            for screen in QApplication.screens():
                if current_rect.intersects(screen.availableGeometry()):
                    is_on_screen = True
                    break

            if not is_on_screen:
                print("  Сохраненное положение окна вне экрана. Перемещаю в центр активного экрана.")
                self.move_to_active_screen_center()
            else:
                print("  Геометрия окна успешно восстановлена.")
        else:
            print("  Сохраненная геометрия не найдена. Центрирую окно на активном экране.")
            self.move_to_active_screen_center()

        self.setWindowOpacity(0.0)

    def showEvent(self, event):
        """
        Обработчик события показа окна.
        Здесь мы запускаем анимацию размера, прозрачности и позиции.
        """
        super().showEvent(event)

        target_size = self.calculate_target_geometry()

        current_pos = self.pos()
        current_size = self.size()

        start_width = int(target_size.width() * 0.9)
        start_height = int(target_size.height() * 0.9)
        start_size_for_animation = QSize(start_width, start_height)

        start_x_for_animation = current_pos.x() + (current_size.width() - start_width) // 2
        start_y_for_animation = current_pos.y() + (current_size.height() - start_height) // 2
        start_pos_for_animation = QPoint(start_x_for_animation, start_y_for_animation)

        self.size_animation.setStartValue(start_size_for_animation)
        self.size_animation.setEndValue(target_size)

        self.pos_animation.setStartValue(start_pos_for_animation)
        self.pos_animation.setEndValue(current_pos)

        self.size_animation.start()
        self.opacity_animation.start()
        self.pos_animation.start()

    def resizeEvent(self, event):
        """
        Обработчик события изменения размера окна.
        Перерисовывает текущий кадр, чтобы он масштабировался под новый размер окна.
        """
        if self._current_cv_frame is not None:
            h, w, ch = self._current_cv_frame.shape
            bytes_per_line = ch * w

            qt_image = QImage(self._current_cv_frame.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

            p = qt_image.scaled(self.image_label.width(), self.image_label.height(), Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            self.image_label.setPixmap(QPixmap.fromImage(p))
        super().resizeEvent(event)

    def closeEvent(self, event):
        """
        Обработчик события закрытия окна.
        Сворачивает окно в трей вместо закрытия и сохраняет состояние.
        """
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("minimizedToTray", True)
        print("Состояние окна сохранено (свернуто в трей).")
        self.hide()
        self.tray_icon.showMessage(
            "Виртуальная Камера Reactive",
            "Приложение свернуто в системный трей.",
            QSystemTrayIcon.Information,
            2000
        )
        event.ignore()

    def tray_activated(self, reason):
        """
        Обработчик события активации иконки в трее.
        При левом клике показывает окно, при правом клике - анимированное меню.
        """
        print(f"Tray activated reason: {reason}")
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()
        elif reason == QSystemTrayIcon.Context:
            if not self.tray_menu.isVisible():
                cursor_pos = QCursor.pos()

                self.tray_menu.adjustSize()
                menu_size = self.tray_menu.sizeHint()

                popup_x = cursor_pos.x()
                popup_y = cursor_pos.y() - menu_size.height()

                screen_rect = QApplication.primaryScreen().availableGeometry()
                popup_x = max(screen_rect.left(), min(popup_x, screen_rect.right() - menu_size.width()))
                popup_y = max(screen_rect.top(), min(popup_y, screen_rect.bottom() - menu_size.height()))

                self.tray_menu.popup(QPoint(popup_x, popup_y))
            else:
                print("Tray menu is already visible, ignoring context activation.")

    def show_window(self):
        """Показывает окно приложения."""
        self.show()
        self.activateWindow()
        self.raise_()

    def quit_app(self):
        """Полностью закрывает приложение и освобождает ресурсы."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("minimizedToTray", False)
        print("Состояние окна сохранено (выход из приложения).")
        QApplication.instance().quit()

    def update_image(self, frame_rgb):
        """
        Обновляет изображение в QLabel.
        Ожидает кадр NumPy в формате RGB.
        """
        if frame_rgb is None:
            return

        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w

        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

        p = qt_image.scaled(self.image_label.width(), self.image_label.height(), Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
        self.image_label.setPixmap(QPixmap.fromImage(p))

        self._current_cv_frame = frame_rgb

    def _handle_status_update_on_gui_thread(self, status_message: str, debug_message: str): # Updated signature to match signal
        """
        Внутренний метод для обработки обновления статуса в GUI-потоке.
        Обновляет внутреннее состояние.
        Анимация будет отображаться через virtual_camera и поступать в display_queue.
        """
        print(f"DEBUG GUI (_handle_status_update_on_gui_thread): Received status='{status_message}'")
        self.status = status_message # Update GUI's internal status
        # НЕ вызываем _update_demo_image_with_status_circle() здесь.
        # Фактические обновления кадров поступают из check_for_new_frame, извлекающего данные из display_queue.

    def check_for_new_frame(self):
        """
        Проверяет очередь на наличие новых кадров из виртуальной камеры.
        Если кадров нет, использует последний отображенный кадр (демо или реальный).
        """
        try:
            frame_rgb = virtual_camera.display_queue.get_nowait()
            self.update_image_signal.emit(frame_rgb)
            # print("DEBUG GUI (check_for_new_frame): Pulled new frame from queue.") # Отладочный вывод
        except queue.Empty:
            # print("DEBUG GUI (check_for_new_frame): Queue empty.") # Отладочный вывод
            pass # Нет нового кадра, продолжаем отображать старый

    def _update_demo_image_with_status_circle(self):
        """
        Генерирует демонстрационное изображение для окна предварительного просмотра,
        используя фоновое изображение пользователя и аватар.
        Этот метод предназначен для установки *начального* кадра в окне.
        """
        print(f"DEBUG GUI (_update_demo_image_with_status_circle): Generating initial demo image for status '{self.status}'.")
        preview_frame_rgb = virtual_camera.get_static_preview_frame(self.status)

        if preview_frame_rgb is not None:
            self.update_image_signal.emit(preview_frame_rgb)
        else:
            print("ПРЕДУПРЕЖДЕНИЕ: virtual_camera.get_static_preview_frame() вернул None при инициализации.")

    # Метод _print_status_to_console и его логика более не нужны здесь.
    # Он был удален, так как логирование теперь полностью обрабатывается logging_manager.py.
    # Чтобы избежать AttributeError, убедитесь, что все ссылки на него удалены.


class CustomStatusHandler(QObject):
    # Теперь сигнал должен передавать оба сообщения, как и в voice_status_callback
    status_display_signal = pyqtSignal(str, str)
    # console_print_signal = pyqtSignal(str, str) # Этот сигнал удален, так как прямая печать в консоль больше не нужна

    def __init__(self, gui_status_callback):
        super().__init__()
        # Подключаем сигнал к методу, который будет обрабатывать GUI-обновления
        self.status_display_signal.connect(gui_status_callback, Qt.QueuedConnection)
        print(
            f"DEBUG CustomStatusHandler (init): status_display_signal connected to {gui_status_callback.__name__} with Qt.QueuedConnection.")
        # УДАЛЕНО: self.console_print_signal.connect(self._print_status_to_console)
        # Эта строка удалена, так как console_print_signal больше не существует в CustomStatusHandler.

        # УДАЛЕНО: self._last_printed_full_message = ""
        # УДАЛЕНО: sys.stdout.write("\n\n")
        # УДАЛЕНО: sys.stdout.flush()

    def on_status_change(self, status_message: str, debug_message: str):
        """
        Этот метод вызывается из потока Playwright (через virtual_camera.voice_status_callback).
        Эмитирует сигналы для обновления GUI и вывода в лог-файл.
        """
        self.status_display_signal.emit(status_message, debug_message) # Emit both messages
        # Прямая печать в консоль с ANSI-кодами или управление курсором больше не нужны.
        # Все print() вызовы автоматически перенаправляются в лог через logging_manager.
        print(f"Статус голоса: {status_message}")
        print(f"[Debug Python] {debug_message}")


def start_gui():
    app = QApplication(sys.argv)
    window = CameraWindow()
    window.show()

    print(f"DEBUG start_gui: Connecting virtual_camera status callback to: {window.status_handler.on_status_change}")
    virtual_camera.set_status_callback(window.status_handler.on_status_change)
    print("DEBUG start_gui: virtual_camera status callback connected.")

    def run_virtual_camera_asyncio():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print("DEBUG run_virtual_camera_asyncio: Starting virtual camera loop...")
        # Теперь вызываем новую функцию, которая только запускает цикл отправки кадров
        loop.run_until_complete(virtual_camera.start_frame_sending_loop())
        print("DEBUG run_virtual_camera_asyncio: Virtual camera loop finished.")
        loop.close()

    camera_thread = threading.Thread(target=run_virtual_camera_asyncio)
    camera_thread.daemon = True
    camera_thread.start()

    sys.exit(app.exec_())


if __name__ == '__main__':
    # Настраиваем логирование в файл как можно раньше
    logging_manager.setup_logging()
    # Устанавливаем кастомный обработчик исключений, чтобы они тоже писались в лог
    sys.excepthook = logging_manager.handle_exception

    create_placeholder_images_for_gui()
    print("\nИнициализация виртуальной камеры (предварительная загрузка всех аватаров и фонов) при прямом запуске gui_elements.py...")
    virtual_camera.initialize_virtual_camera()
    print("Виртуальная камера инициализирована, ресурсы загружены.")
    start_gui()
