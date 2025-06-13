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
    QPushButton, QSizePolicy, QDesktopWidget, QGraphicsOpacityEffect, QLineEdit, QMessageBox, QFormLayout, QCheckBox, \
    QSlider, QComboBox, QSpacerItem
from PyQt5.QtGui import QPixmap, QImage, QIcon, QPalette, QBrush, QColor, QScreen, QCursor, QFont
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint, QPropertyAnimation, QEasingCurve, QSize, QSettings

# Импортируем virtual_camera как модуль, чтобы получить доступ к display_queue и CAM_WIDTH/HEIGHT
import virtual_camera
import \
    reactive_monitor  # Предполагается, что reactive_monitor существует и вызывает virtual_camera.voice_status_callback
import utils  # Предполагается, что utils существует
import logging_manager  # Добавляем импорт logging_manager
import config_manager  # Импортируем config_manager для доступа к настройкам

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


class SettingsWindow(QWidget):
    """
    Окно для настройки параметров из config.txt.
    """
    # Define a default config for reset functionality.
    # These should match the defaults in config_manager.py's load_config()
    DEFAULT_CONFIG = {
        'CROSS_FADE_ENABLED': 'True',
        'BOUNCING_ENABLED': 'True',
        'CAM_FPS': '60',  # Изменено на '60'
        'CAM_WIDTH': '640',
        'CAM_HEIGHT': '360',
        'CROSS_FADE_DURATION_MS': '200',
        'RESET_ANIMATION_ON_STATUS_CHANGE': 'True',
        'INSTANT_TALK_TRANSITION': 'True',
        'DIM_ENABLED': 'True',
        'DIM_PERCENTAGE': '50'
    }

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Настройки")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # Окно-контейнер прозрачное

        self._closing_via_button = False  # Флаг для контроля закрытия окна

        # Основной layout для SettingsWindow (будет содержать content_widget)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)  # Убираем отступы для контейнера
        outer_layout.setSpacing(0)

        # Создаем внутренний виджет, который будет содержать все содержимое
        self.content_widget = QWidget(self)
        self.content_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(26, 26, 26, 255); /* Полностью непрозрачный фон для содержимого */
                border-radius: 12px; /* Скругление углов для внутреннего виджета */
                color: #ffffff;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
            }
            QLabel { /* Стиль для текста параметров */
                font-weight: bold; /* Жирный текст */
            }
            QLineEdit {
                background-color: #333333;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 3px 5px; /* Уменьшен padding для уменьшения высоты */
                min-height: 24px; /* Устанавливаем минимальную высоту */
                color: #ffffff;
                text-align: right; /* Выравнивание текста вправо */
            }
            QPushButton {
                background-color: #007bff;
                color: #ffffff;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton#closeButton, QPushButton#resetButton { /* Applied style to reset button too */
                background-color: #6c757d;
            }
            QPushButton#closeButton:hover, QPushButton#resetButton:hover {
                background-color: #5a6268;
            }
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px; /* the groove height */
                background: #555555;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #007bff;
                border: 1px solid #007bff;
                width: 18px;
                height: 18px; /* Сделать handle квадратным */
                margin: -5px 0; /* Отступ для центрирования */
                border-radius: 9px; /* Сделать handle круглым (половина ширины/высоты) */
            }
            QComboBox {
                background-color: #333333;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 3px 5px; /* Уменьшен padding для уменьшения высоты */
                min-height: 24px; /* Устанавливаем минимальную высоту */
                color: #ffffff;
                text-align: right; /* Выравнивание текста вправо */
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                /* Используем простой SVG для стрелки вниз */
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDE2IDE2Ij48cGF0aCBmaWxsPSJ3aGl0ZSIgZD0iTTAgNWw4IDhsOC04eiIvPjwvc3ZnPg==);
                width: 16px;
                height: 16px;
            }
            QComboBox QAbstractItemView {
                background-color: #333333;
                border: 1px solid #555555;
                selection-background-color: #0099ff; /* Слегка осветленный синий для выбора */
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 18px; /* Примерный размер для индикатора чекбокса */
                height: 18px;
            }
            QCheckBox {
                min-height: 24px; /* Устанавливаем минимальную высоту для чекбокса */
                spacing: 5px; /* Добавляем небольшой отступ между квадратом и текстом */
            }

        """)
        outer_layout.addWidget(self.content_widget)  # Добавляем внутренний виджет в layout родителя

        # Все содержимое теперь будет в layout'е content_widget
        main_layout = QVBoxLayout(self.content_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        title_label = QLabel("Настройки", self.content_widget)  # Изменено на "Настройки"
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        main_layout.addWidget(title_label)

        self.form_layout = QFormLayout()
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setHorizontalSpacing(15)
        self.form_layout.setVerticalSpacing(10)

        self.config_widgets = {}  # Словарь для хранения виджетов для каждой настройки

        self.current_config = config_manager.load_config()

        # Параметры, которые будут отображаться и редактироваться (из USER_CONFIG_FILE)
        cam_fps_label = QLabel("Частота кадров (FPS):")
        self.cam_fps_input = QLineEdit(str(self.current_config.get('CAM_FPS', self.DEFAULT_CONFIG['CAM_FPS'])))
        self.cam_fps_input.setAlignment(Qt.AlignRight)  # Выравнивание текста вправо
        self.config_widgets['CAM_FPS'] = self.cam_fps_input
        self.form_layout.addRow(cam_fps_label, self.cam_fps_input)

        # Разрешение камеры (CAM_WIDTH, CAM_HEIGHT)
        self.resolution_options = [
            (640, 360), (854, 480), (1280, 720), (1920, 1080), (3840, 2160)
        ]
        self.resolution_names = [f"{w}x{h}" for w, h in self.resolution_options]

        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(self.resolution_names)

        current_res_w = self.current_config.get('CAM_WIDTH', self.DEFAULT_CONFIG['CAM_WIDTH'])
        current_res_h = self.current_config.get('CAM_HEIGHT', self.DEFAULT_CONFIG['CAM_HEIGHT'])
        current_res_str = f"{current_res_w}x{current_res_h}"

        if current_res_str in self.resolution_names:
            self.resolution_combo.setCurrentText(current_res_str)
        else:
            # Если текущее разрешение не в списке, добавляем его и выбираем
            self.resolution_combo.addItem(current_res_str)
            self.resolution_combo.setCurrentText(current_res_str)

        self.config_widgets['RESOLUTION'] = self.resolution_combo
        self.form_layout.addRow(QLabel("Разрешение Камеры:"), self.resolution_combo)

        # Boolean параметры с чекбоксами
        bool_params_map = {
            'CROSS_FADE_ENABLED': 'Включить плавный переход:',
            'BOUNCING_ENABLED': 'Включить эффект "подпрыгивания":',
            'RESET_ANIMATION_ON_STATUS_CHANGE': 'Сбрасывать анимацию при смене статуса:',
            'INSTANT_TALK_TRANSITION': 'Мгновенный переход в статус "Говорит":',
            'DIM_ENABLED': 'Включить затемнение при молчании:'
        }
        for param_key, display_text in bool_params_map.items():
            checkbox = QCheckBox()
            checkbox.setChecked(
                self.current_config.get(param_key, self.DEFAULT_CONFIG.get(param_key, 'False')).lower() == 'true')

            # Создаем QHBoxLayout для выравнивания чекбокса вправо
            checkbox_layout = QHBoxLayout()
            checkbox_layout.addStretch()  # Отталкиваем чекбокс вправо
            checkbox_layout.addWidget(checkbox)

            self.config_widgets[param_key] = checkbox
            self.form_layout.addRow(QLabel(display_text), checkbox_layout)

        # DIM_PERCENTAGE с инвертированной логикой для "Яркость затемненного"
        dim_percentage_label = QLabel("Яркость затемненного:")
        dim_percentage_layout = QHBoxLayout()

        self.dim_percentage_slider = QSlider(Qt.Horizontal)
        self.dim_percentage_slider.setRange(0, 100)
        self.dim_percentage_slider.setSingleStep(1)

        # Инвертируем значение: 100 - текущий процент затемнения = яркость
        initial_dim_percent_val = int(self.current_config.get('DIM_PERCENTAGE', self.DEFAULT_CONFIG['DIM_PERCENTAGE']))
        self.dim_percentage_slider.setValue(100 - initial_dim_percent_val)

        self.dim_percentage_input = QLineEdit(str(100 - initial_dim_percent_val))
        self.dim_percentage_input.setFixedWidth(50)  # Небольшая ширина для поля ввода числа
        self.dim_percentage_input.setAlignment(Qt.AlignRight)  # Выравнивание текста вправо

        self.dim_percentage_slider.valueChanged.connect(lambda value: self.dim_percentage_input.setText(str(value)))
        self.dim_percentage_input.textChanged.connect(self.update_dim_percentage_slider_from_input)

        dim_percentage_layout.addWidget(self.dim_percentage_slider)
        dim_percentage_layout.addSpacing(10)  # Отступ между ползунком и полем ввода
        dim_percentage_layout.addWidget(self.dim_percentage_input)
        self.config_widgets['DIM_PERCENTAGE'] = {'slider': self.dim_percentage_slider,
                                                 'input': self.dim_percentage_input}
        self.form_layout.addRow(dim_percentage_label, dim_percentage_layout)

        cross_fade_duration_label = QLabel("Длительность плавного перехода (мс):")
        self.cross_fade_duration_input = QLineEdit(
            str(self.current_config.get('CROSS_FADE_DURATION_MS', self.DEFAULT_CONFIG['CROSS_FADE_DURATION_MS'])))
        self.cross_fade_duration_input.setAlignment(Qt.AlignRight)  # Выравнивание текста вправо
        self.config_widgets['CROSS_FADE_DURATION_MS'] = self.cross_fade_duration_input
        self.form_layout.addRow(cross_fade_duration_label, self.cross_fade_duration_input)

        main_layout.addLayout(self.form_layout)

        button_layout = QHBoxLayout()

        self.save_message_label = QLabel("", self.content_widget)  # Label for save message
        self.save_message_label.setStyleSheet("color: #00ff00; font-weight: bold; margin-right: 10px;")  # Green text
        self.save_message_label.setMinimumWidth(100)  # Fixed width to prevent layout shift
        self.save_message_label.hide()  # Hide initially
        button_layout.addWidget(self.save_message_label)
        button_layout.addStretch()

        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.save_settings)
        button_layout.addWidget(save_button)

        # Переименована кнопка "Отмена" в "Закрыть"
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("closeButton")  # Используем id для стилей
        close_button.clicked.connect(self._trigger_close_via_button)  # Связываем с новой функцией закрытия
        button_layout.addWidget(close_button)

        # Кнопка "Сбросить" (ранее "Сбросить настройки"), теперь справа от "Закрыть"
        reset_button = QPushButton("Сбросить")
        reset_button.setObjectName("resetButton")  # Object name for styling
        reset_button.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_button)

        main_layout.addLayout(button_layout)

        self.setMinimumSize(350, 400)

        self.start_pos = None
        self.settings = QSettings("ReactivePlus", "VirtualCameraReactiveSettings")

    def update_dim_percentage_slider_from_input(self, text):
        """Обновляет ползунок DIM_PERCENTAGE при изменении текста в поле ввода."""
        try:
            value = int(text)
            if 0 <= value <= 100:
                self.dim_percentage_slider.setValue(value)
            else:
                self.dim_percentage_input.setText(str(self.dim_percentage_slider.value()))
        except ValueError:
            # Если текст не является числом, сбрасываем поле ввода
            self.dim_percentage_input.setText(str(self.dim_percentage_slider.value()))

    def _trigger_close_via_button(self):
        """Устанавливает флаг и вызывает закрытие окна."""
        self._closing_via_button = True
        self.close()

    def closeEvent(self, event):
        """
        Переопределенный обработчик события закрытия окна.
        Разрешает закрытие только по явному клику на кнопку "Закрыть".
        """
        if self._closing_via_button:
            event.accept()
        else:
            event.ignore()
            QMessageBox.warning(self, "Закрытие окна",
                                "Пожалуйста, используйте кнопку 'Закрыть' для выхода из настроек.")
            self._closing_via_button = False  # Сбрасываем флаг на всякий случай

    def load_settings_into_gui(self, config_data):
        """Загружает настройки из словаря config_data в виджеты GUI."""
        self.cam_fps_input.setText(str(config_data.get('CAM_FPS', self.DEFAULT_CONFIG['CAM_FPS'])))

        current_res_w = config_data.get('CAM_WIDTH', self.DEFAULT_CONFIG['CAM_WIDTH'])
        current_res_h = config_data.get('CAM_HEIGHT', self.DEFAULT_CONFIG['CAM_HEIGHT'])
        current_res_str = f"{current_res_w}x{current_res_h}"
        # If the resolution from config_data is not in the predefined list, add it first.
        if current_res_str not in self.resolution_names:
            # Temporarily add it if it's not a default, to allow setting it.
            self.resolution_combo.addItem(current_res_str)
        self.resolution_combo.setCurrentText(current_res_str)
        # Optional: remove the dynamically added item if it's not a real option after setting
        # This part is omitted for simplicity, as the problem implies valid resolutions.

        bool_params_map = {
            'CROSS_FADE_ENABLED': 'Включить плавный переход:',
            'BOUNCING_ENABLED': 'Включить эффект "подпрыгивания":',
            'RESET_ANIMATION_ON_STATUS_CHANGE': 'Сбрасывать анимацию при смене статуса:',
            'INSTANT_TALK_TRANSITION': 'Мгновенный переход в статус "Говорит":',
            'DIM_ENABLED': 'Включить затемнение при молчании:'
        }
        for param_key in bool_params_map:
            checkbox = self.config_widgets[param_key]
            checkbox.setChecked(
                config_data.get(param_key, self.DEFAULT_CONFIG.get(param_key, 'False')).lower() == 'true')

        initial_dim_percent_val = int(config_data.get('DIM_PERCENTAGE', self.DEFAULT_CONFIG['DIM_PERCENTAGE']))
        self.dim_percentage_slider.setValue(100 - initial_dim_percent_val)
        self.dim_percentage_input.setText(str(100 - initial_dim_percent_val))

        self.cross_fade_duration_input.setText(
            str(config_data.get('CROSS_FADE_DURATION_MS', self.DEFAULT_CONFIG['CROSS_FADE_DURATION_MS'])))

    def reset_settings(self):
        """Сбрасывает все настройки к значениям по умолчанию."""
        self.load_settings_into_gui(self.DEFAULT_CONFIG)
        # Удалены строки, которые отображали сообщение "Настройки сброшены!"
        # self.save_message_label.setText("Настройки сброшены!") # Display reset message
        # self.save_message_label.show()
        # QTimer.singleShot(2000, self.save_message_label.hide) # Hide after 2 seconds

    def load_window_state(self):
        """Загружает сохраненное положение окна настроек."""
        geometry_data = self.settings.value("geometry")
        if geometry_data:
            self.restoreGeometry(geometry_data)
            is_on_screen = False
            current_rect = self.frameGeometry()
            for screen in QApplication.screens():
                if current_rect.intersects(screen.availableGeometry()):
                    is_on_screen = True
                    break
            if not is_on_screen:
                self.center_on_primary_screen()
        else:
            self.center_on_primary_screen()

    def save_window_state(self):
        """Сохраняет текущее положение окна настроек."""
        self.settings.setValue("geometry", self.saveGeometry())

    def center_on_primary_screen(self):
        """Центрирует окно настроек на основном экране."""
        screen_geo = QApplication.primaryScreen().availableGeometry()
        self.move(screen_geo.center() - self.rect().center())

    def position_relative_to_parent(self):
        """
        Позиционирует окно настроек относительно родительского окна (окна камеры).
        Появляется слева/справа или сверху/снизу, чтобы не выходить за границы экрана.
        """
        if not self.parent():
            self.center_on_primary_screen()
            return

        parent_rect = self.parent().frameGeometry()
        self_rect = self.frameGeometry()

        current_screen = QApplication.screenAt(parent_rect.center())
        if current_screen is None:
            current_screen = QApplication.primaryScreen()
        screen_geo = current_screen.availableGeometry()

        y_aligned_with_parent = parent_rect.top() + (parent_rect.height() - self_rect.height()) // 2

        candidate_positions = []

        pos_right_x = parent_rect.right() + 10
        if (pos_right_x + self_rect.width()) <= screen_geo.right():
            candidate_positions.append({'x': pos_right_x, 'y': y_aligned_with_parent, 'side': 'right'})

        pos_left_x = parent_rect.left() - self_rect.width() - 10
        if pos_left_x >= screen_geo.left():
            candidate_positions.append({'x': pos_left_x, 'y': y_aligned_with_parent, 'side': 'left'})

        off_screen_bottom_px = max(0, parent_rect.bottom() - screen_geo.bottom())
        is_parent_mostly_off_bottom = (parent_rect.height() > 0 and off_screen_bottom_px / parent_rect.height() > 0.5)

        pos_top_x_centered = parent_rect.center().x() - self_rect.width() // 2
        pos_top_y = parent_rect.top() - self_rect.height() - 10
        if is_parent_mostly_off_bottom and pos_top_y >= screen_geo.top():
            candidate_positions.append({'x': pos_top_x_centered, 'y': pos_top_y, 'side': 'top'})

        pos_bottom_x_centered = parent_rect.center().x() - self_rect.width() // 2
        pos_bottom_y = parent_rect.bottom() + 10
        if (pos_bottom_y + self_rect.height()) <= screen_geo.bottom():
            if not is_parent_mostly_off_bottom:
                candidate_positions.append({'x': pos_bottom_x_centered, 'y': pos_bottom_y, 'side': 'bottom'})

        chosen_x, chosen_y = screen_geo.center().x() - self_rect.width() // 2, screen_geo.center().y() - self_rect.height() // 2

        if candidate_positions:
            best_candidate = None
            max_free_space = -1

            if is_parent_mostly_off_bottom and any(c['side'] == 'top' for c in candidate_positions):
                best_candidate = next(c for c in candidate_positions if c['side'] == 'top')
            else:
                for cand in candidate_positions:
                    if cand['side'] in ['left', 'right']:
                        space_on_side = (screen_geo.right() - parent_rect.right()) if cand['side'] == 'right' else (
                                    parent_rect.left() - screen_geo.left())
                        if space_on_side > max_free_space:
                            max_free_space = space_on_side
                            best_candidate = cand

                if not best_candidate:
                    for cand in candidate_positions:
                        if cand['side'] in ['top', 'bottom']:
                            if cand['side'] == 'top' and pos_top_y >= screen_geo.top():
                                best_candidate = cand
                                break
                            elif cand['side'] == 'bottom' and (
                                    pos_bottom_y + self_rect.height()) <= screen_geo.bottom():
                                best_candidate = cand
                                break

            if best_candidate:
                chosen_x, chosen_y = best_candidate['x'], best_candidate['y']

        chosen_x = max(screen_geo.left(), min(chosen_x, screen_geo.right() - self_rect.width()))
        chosen_y = max(screen_geo.top(), min(chosen_y, screen_geo.bottom() - self_rect.height()))

        self.move(chosen_x, chosen_y)

    def mousePressEvent(self, event):
        """Начало перетаскивания окна."""
        if event.button() == Qt.LeftButton:
            if self.content_widget:
                self.start_pos = event.globalPos() - self.content_widget.mapToGlobal(QPoint(0, 0))
            else:
                self.start_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Перетаскивание окна."""
        if event.buttons() == Qt.LeftButton and self.start_pos is not None:
            self.move(event.globalPos() - self.start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Окончание перетаскивания."""
        self.start_pos = None
        event.accept()

    def closeEvent(self, event):
        """
        Обработчик события закрытия окна настроек.
        Сохраняет положение, если основное окно свернуто.
        """
        if self.parent() and (self.parent().isHidden() or self.parent().isMinimized()):
            self.save_window_state()
        super().closeEvent(event)

    def save_settings(self):
        """Сохраняет измененные настройки в config.txt и применяет их."""
        updated_config = self.current_config.copy()

        # Сохранение CAM_FPS
        try:
            updated_config['CAM_FPS'] = self.cam_fps_input.text()
        except KeyError:
            pass  # Если поле не найдено, ничего не делаем

        # Сохранение CAM_WIDTH, CAM_HEIGHT из QComboBox
        selected_res = self.resolution_combo.currentText()
        try:
            width, height = map(int, selected_res.split('x'))
            updated_config['CAM_WIDTH'] = str(width)
            updated_config['CAM_HEIGHT'] = str(height)
        except ValueError:
            QMessageBox.warning(self, "Ошибка ввода", "Неверный формат разрешения. Используйте WxH.")
            return
        except KeyError:
            pass  # Если поля не найдены, ничего не делаем

        # Сохранение Boolean параметров
        bool_params = [
            'CROSS_FADE_ENABLED',
            'BOUNCING_ENABLED',
            'RESET_ANIMATION_ON_STATUS_CHANGE',
            'INSTANT_TALK_TRANSITION',
            'DIM_ENABLED'
        ]
        for param_key in bool_params:
            try:
                checkbox = self.config_widgets[param_key]
                updated_config[param_key] = 'True' if checkbox.isChecked() else 'False'
            except KeyError:
                pass  # Если виджет не найден, ничего не делаем

        # Сохранение DIM_PERCENTAGE (инвертированное значение)
        try:
            current_brightness = int(self.dim_percentage_input.text())
            updated_config['DIM_PERCENTAGE'] = str(100 - current_brightness)  # Сохраняем как затемнение
        except KeyError:
            pass  # Если поле не найдено, ничего не делаем
        except ValueError:
            QMessageBox.warning(self, "Ошибка ввода",
                                "Неверный формат для 'Яркость затемненного'. Используйте число от 0 до 100.")
            return

        # Сохранение CROSS_FADE_DURATION_MS
        try:
            updated_config['CROSS_FADE_DURATION_MS'] = self.cross_fade_duration_input.text()
        except KeyError:
            pass  # Если поле не найдено, ничего не делаем

        try:
            config_manager.save_config(updated_config)
            self.save_message_label.setText("Сохранено!")
            self.save_message_label.show()
            QTimer.singleShot(2000, self.save_message_label.hide)  # Hide after 2 seconds
            virtual_camera.initialize_virtual_camera()
            # No self.close() here as requested by user
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить настройки: {e}")


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
        self.settings_window = None

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#1a1a1a"))  # Более темный цвет
        self.setPalette(palette)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a; /* Более темный цвет */
                color: #ffffff;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
                border-top-left-radius: 12px; /* Скругление верхних углов */
                border-top-right-radius: 12px; /* Скругление верхних углов */
            }
            QLabel { /* Для title_label */
                font-family: "Segoe UI", sans-serif;
                font-size: 11px; /* Изменен размер шрифта */
                font-weight: bold;
            }
            QPushButton {
                background-color: transparent; /* Default transparent */
                color: #ffffff;
                border: none;
                padding: 5px 10px;
                margin: 0px;
                min-width: 30px;
                font-weight: bold;
                border-radius: 0px;
                font-family: "Segoe UI", "Arial", sans-serif;
                font-size: 14px; /* Увеличен размер иконок */
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton#settingsButton { /* Specific style for settings button */
                background-color: transparent; /* Changed to transparent */
                color: #ffffff; /* White text */
                font-size: 14px; /* Maintain icon size */
            }
            QPushButton#settingsButton:hover {
                background-color: rgba(255, 255, 255, 0.1); /* Lighter grey on hover */
            }
            QPushButton#closeButton:hover {
                background-color: #e81123;
            }
            QPushButton#quitButton {
                border-top-right-radius: 10px;
            }
            QPushButton#quitButton:hover {
                background-color: #e81123;
            }
        """)
        self.setFixedHeight(25)  # Изменена высота до 25 пикселей

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)  # Смещен вправо на 5 пикселей (было 5, стало 10)
        layout.setSpacing(0)

        self.icon_label = QLabel(self)
        if os.path.exists(ICON_PATH):
            pixmap = QPixmap(ICON_PATH).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pixmap)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(WINDOW_TITLE, self)
        layout.addWidget(self.title_label)

        layout.addStretch()

        # Кнопка "Настройки" (значок)
        self.settings_button = QPushButton("⚙", self)  # Вернул значок
        self.settings_button.setObjectName("settingsButton")  # Object name for styling
        self.settings_button.clicked.connect(self.open_settings_window)
        self.settings_button.setToolTip("Настройки")
        layout.addWidget(self.settings_button)

        self.minimize_button = QPushButton("—", self)
        self.minimize_button.clicked.connect(self.parent_window.showMinimized)
        self.minimize_button.setToolTip("Свернуть")
        layout.addWidget(self.minimize_button)

        # Кнопка "Развернуть/Восстановить" с Unicode символами
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

    def open_settings_window(self):
        """Открывает или скрывает окно настроек."""
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.parent_window)

        if self.settings_window.isVisible():
            self.settings_window.hide()
        else:
            # Загружаем/позиционируем в зависимости от состояния основного окна
            if self.parent_window.isHidden() or self.parent_window.isMinimized():
                # Если основное окно свернуто, пытаемся восстановить предыдущую позицию настроек
                self.settings_window.load_window_state()
            else:
                # Если основное окно видимо, позиционируем относительно него
                self.settings_window.position_relative_to_parent()

            self.settings_window.show()
            self.settings_window.activateWindow()
            self.settings_window.raise_()

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
            self.maximize_restore_button.setText("🗗")  # Символ "Восстановить"
            self.maximize_restore_button.setToolTip("Восстановить")

        self.parent_window._update_main_container_style()  # Обновляем стиль главного контейнера

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
        if self.opacity_animation.state() == QPropertyAnimation.Running:
            self.opacity_animation.stop()

        self.opacity_effect.setOpacity(0.0)

        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
        except TypeError:
            pass

        super().popup(pos, action)

        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.start()

    def _start_fade_out(self):
        """
        Запускает анимацию скрытия меню.
        """
        if self.opacity_animation.state() == QPropertyAnimation.Running and self.opacity_animation.endValue() == 0.0:
            return

        if self.opacity_animation.state() == QPropertyAnimation.Running:
            self.opacity_animation.stop()

        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
        except TypeError:
            pass

        self.opacity_animation.setStartValue(self.opacity_effect.opacity())
        self.opacity_animation.setEndValue(0.0)

        self.opacity_animation.finished.connect(self._actual_hide)
        self.opacity_animation.start()

    def _actual_hide(self):
        """
        Скрывает меню после завершения анимации исчезновения.
        """
        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
        except TypeError:
            pass
        self.hide()


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
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Файл иконки '{ICON_PATH}' не найден. Окно будет без иконки.")

        main_window_layout = QVBoxLayout(self)
        main_window_layout.setContentsMargins(0, 0, 0, 0)
        main_window_layout.setSpacing(0)

        self.main_container_widget = QWidget(self)
        # Стиль для скругления углов, будет обновляться динамически
        self.main_container_widget.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-radius: 12px;
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
        # Скругление углов для image_label
        self.image_label.setStyleSheet("background-color: black; border-radius: 12px;")
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
        self.pos_animation.setStartValue(QPoint(0, 0))  # Инициализируем, так как он может быть None
        self.pos_animation.setEndValue(QPoint(0, 0))  # Инициализируем, так как он может быть None
        self.pos_animation.setEasingCurve(QEasingCurve.OutQuad)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(ICON_PATH))
        self.tray_icon.activated.connect(self.tray_activated)

        self.tray_menu = AnimatedMenu(self)
        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self.show_window)
        self.tray_menu.addAction(show_action)

        # Добавляем действие для открытия настроек в трей-меню
        settings_action = QAction("Настройки", self)
        settings_action.triggered.connect(lambda: self.title_bar.open_settings_window())
        self.tray_menu.addAction(settings_action)

        self.tray_menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(quit_action)

        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: transparent;
                border-radius: 0px;
                border: none;
                font-family: "Segoe UI", sans-serif;
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

        min_height_fixed_elements = self.title_bar.height() + \
                                    self.content_inner_widget.layout().contentsMargins().top() + \
                                    self.content_inner_widget.layout().contentsMargins().bottom()

        self.setMinimumSize(160, min_height_fixed_elements + 100)

        self._current_cv_frame = None

        self.status_handler = CustomStatusHandler(self._handle_status_update_on_gui_thread)

        self.settings = QSettings("ReactivePlus", "VirtualCameraReactive")
        self.load_window_state()

        self._update_main_container_style()  # Устанавливаем начальный стиль углов
        self._update_demo_image_with_status_circle()

    def _update_main_container_style(self):
        """Обновляет стиль main_container_widget в зависимости от состояния окна."""
        if self.isMaximized():
            self.main_container_widget.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border-radius: 0px; /* Убираем скругление при максимизации */
                }
            """)
        else:
            self.main_container_widget.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border-radius: 12px; /* Скругление в нормальном состоянии */
                }
            """)

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
        minimized_to_tray = self.settings.value("minimizedToTray", False, type=bool)

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
            self.restoreGeometry(geometry_data)

            is_on_screen = False
            current_rect = self.frameGeometry()
            for screen in QApplication.screens():
                if current_rect.intersects(screen.availableGeometry()):
                    is_on_screen = True
                    break

            if not is_on_screen:
                self.move_to_active_screen_center()
        else:
            self.move_to_active_screen_center()

        self.setWindowOpacity(0.0)

    def showEvent(self, event):
        """
        Обработчик события показа окна.
        Здесь мы запускаем анимацию размера, прозрачности и позиции.
        """
        super().showEvent(event)
        self._update_main_container_style()  # Обновляем стиль углов при показе

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
                pass  # Menu is already visible

    def show_window(self):
        """Показывает окно приложения."""
        self.show()
        self.activateWindow()
        self.raise_()

    def quit_app(self):
        """Полностью закрывает приложение и освобождает ресурсы."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("minimizedToTray", False)
        QApplication.instance().quit()

    def update_image(self, frame_rgb):
        """
        Обновляет изображение в QLabel.
        Ожидает кадр NumPy в формате RGB.
        """
        if frame_rgb is None:
            return

        # Перемещено внутрь блока if для исправления NameError
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w

        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

        p = qt_image.scaled(self.image_label.width(), self.image_label.height(), Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
        self.image_label.setPixmap(QPixmap.fromImage(p))

        self._current_cv_frame = frame_rgb

    def _handle_status_update_on_gui_thread(self, status_message: str, debug_message: str):
        """
        Внутренний метод для обработки обновления статуса в GUI-потоке.
        Обновляет внутреннее состояние.
        Анимация будет отображаться через virtual_camera и поступать в display_queue.
        """
        self.status = status_message

    def check_for_new_frame(self):
        """
        Проверяет очередь на наличие новых кадров из виртуальной камеры.
        Если кадров нет, использует последний отображенный кадр (демо или реальный).
        """
        try:
            frame_rgb = virtual_camera.display_queue.get_nowait()
            self.update_image_signal.emit(frame_rgb)
        except queue.Empty:
            pass

    def _update_demo_image_with_status_circle(self):
        """
        Генерирует демонстрационное изображение для окна предварительного просмотра,
        используя фоновое изображение пользователя и аватар.
        Этот метод предназначен для установки *начального* кадра в окне.
        """
        preview_frame_rgb = virtual_camera.get_static_preview_frame(self.status)

        if preview_frame_rgb is not None:
            self.update_image_signal.emit(preview_frame_rgb)
        else:
            print("ПРЕДУПРЕЖДЕНИЕ: virtual_camera.get_static_preview_frame() вернул None при инициализации.")


class CustomStatusHandler(QObject):
    status_display_signal = pyqtSignal(str, str)

    def __init__(self, gui_status_callback):
        super().__init__()
        self.status_display_signal.connect(gui_status_callback, Qt.QueuedConnection)

    def on_status_change(self, status_message: str, debug_message: str):
        """
        Этот метод вызывается из потока Playwright (через virtual_camera.voice_status_callback).
        Эмитирует сигналы для обновления GUI и вывода в лог-файл.
        """
        self.status_display_signal.emit(status_message, debug_message)


def start_gui():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setQuitOnLastWindowClosed(False)  # Отключаем автоматический выход при закрытии последнего видимого окна

    window = CameraWindow()
    window.show()

    virtual_camera.set_status_callback(window.status_handler.on_status_change)

    def run_virtual_camera_asyncio():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(virtual_camera.start_frame_sending_loop())
        loop.close()

    camera_thread = threading.Thread(target=run_virtual_camera_asyncio)
    camera_thread.daemon = True
    camera_thread.start()

    sys.exit(app.exec_())


if __name__ == '__main__':
    logging_manager.setup_logging()
    sys.excepthook = logging_manager.handle_exception

    create_placeholder_images_for_gui()
    print(
        "\nИнициализация виртуальной камеры (предварительная загрузка всех аватаров и фонов) при прямом запуске gui_elements.py...")
    virtual_camera.initialize_virtual_camera()
    print("Виртуальная камера инициализирована, ресурсы загружены.")
    start_gui()
