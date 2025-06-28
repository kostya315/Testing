import os
import sys
import queue
import cv2
import numpy as np
from PIL import Image
from io import BytesIO
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QSystemTrayIcon, QMenu, QAction, QHBoxLayout,
                             QPushButton, QSizePolicy, QDesktopWidget, QGraphicsOpacityEffect, QLineEdit, QMessageBox,
                             QFormLayout, QCheckBox, QSlider)
from PyQt5.QtGui import QPixmap, QImage, QIcon, QFont, QColor, QPalette, QCursor
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint, QPropertyAnimation, QEasingCurve, QSize, QSettings, \
    pyqtSlot
from PyQt5.QtGui import QIntValidator  # Импорт QIntValidator

from renderer import Renderer
import config_manager
import logging_manager
import virtual_camera  # Импортируем virtual_camera для доступа к CAM_WIDTH/HEIGHT

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WINDOW_TITLE = "Виртуальная Камера Reactive"
ICON_PATH = os.path.join(SCRIPT_DIR, "app_icon.png")
VGA_WIDTH = 640
VGA_HEIGHT = 480


class SettingsWindow(QWidget):
    """
    Окно для настройки параметров из config.txt.
    """
    DEFAULT_CONFIG = {
        'CROSS_FADE_ENABLED': 'True',
        'BOUNCING_ENABLED': 'True',
        'CAM_FPS': '60',
        'CROSS_FADE_DURATION_MS': '200',
        'RESET_ANIMATION_ON_STATUS_CHANGE': 'True',
        'INSTANT_TALK_TRANSITION': 'True',
        'DIM_ENABLED': 'True',
        'DIM_PERCENTAGE': '50',
    }

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)  # Убедимся, что это отдельное окно с рамкой
        self.setWindowTitle("Настройки")
        # Удаляем Qt.FramelessWindowHint, чтобы окно было с рамкой и кнопкой закрытия по умолчанию
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)  # Делаем фон непрозрачным

        self._closing_via_button = False  # Флаг для отслеживания, как окно закрывается

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.content_widget = QWidget(self)
        # Стили из gui_elements_old, адаптированные для текущего проекта
        self.content_widget.setStyleSheet("""
            QWidget {
                background-color: #2e2e2e; /* Более темный фон для настроек */
                border-radius: 8px;
                color: #ffffff;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
            }
            QLabel {
                font-weight: bold;
                color: #e0e0e0;
            }
            QLineEdit {
                background-color: #3f3f3f;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                padding: 3px 5px;
                min-height: 24px;
                color: #ffffff;
                text-align: right;
            }
            QPushButton {
                background-color: #007acc; /* Более приятный синий */
                color: #ffffff;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
            QPushButton#closeButton, QPushButton#resetButton {
                background-color: #555555; /* Серый для закрытия/сброса */
            }
            QPushButton#closeButton:hover, QPushButton#resetButton:hover {
                background-color: #444444;
            }
            QSlider::groove:horizontal {
                border: 1px solid #5a5a5a;
                height: 8px;
                background: #3f3f3f;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #007acc;
                border: 1px solid #007acc;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QComboBox {
                background-color: #3f3f3f;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                padding: 3px 5px;
                min-height: 24px;
                color: #ffffff;
                text-align: right;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDE2IDE2Ij48cGF0aCBmYWxsPSJ3aGl0ZSIgZD0iTTAgNWw4IDhsOC04eiIvPjwvc3ZnPg==);
                width: 16px;
                height: 16px;
            }
            QComboBox QAbstractItemView {
                background-color: #3f3f3f;
                border: 1px solid #5a5a5a;
                selection-background-color: #007acc;
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #5a5a5a;
                border-radius: 3px;
                background-color: #3f3f3f;
            }
            QCheckBox::indicator:checked {
                background-color: #007acc;
                border: 1px solid #007acc;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBkPSJNMjAuMjgzIDQuNzc0TDEwLjIzNiAxNC44MjkgNC43NzQgOC4zNjdMMy4zNjEgOS43ODNMMTAuMjM2IDE2LjY1OEwyMS42OTYgNS4yMDlMMjAuMjgzIDQuNzc0eiIgZmlsbD0id2hpdGUiLz48L3N2Zz4=);
            }
            QCheckBox {
                min-height: 24px;
                spacing: 5px;
                color: #e0e0e0;
            }
        """)
        outer_layout.addWidget(self.content_widget)

        main_layout = QVBoxLayout(self.content_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        title_label = QLabel("Настройки", self.content_widget)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px; color: #ffffff;")
        main_layout.addWidget(title_label)

        self.form_layout = QFormLayout()
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setHorizontalSpacing(15)
        self.form_layout.setVerticalSpacing(10)

        self.config_widgets = {}
        self.current_config = config_manager.load_config()

        # CAM_FPS
        cam_fps_label = QLabel("Частота кадров (FPS):")
        self.cam_fps_input = QLineEdit(str(self.current_config.get('CAM_FPS', self.DEFAULT_CONFIG['CAM_FPS'])))
        self.cam_fps_input.setAlignment(Qt.AlignRight)
        self.cam_fps_input.setValidator(QIntValidator(1, 120))  # Ограничиваем ввод целыми числами от 1 до 120
        self.config_widgets['CAM_FPS'] = self.cam_fps_input
        self.form_layout.addRow(cam_fps_label, self.cam_fps_input)

        # Метка для отображения текущего разрешения камеры (определяется фоном)
        self.current_resolution_display_label = QLabel("Разрешение камеры: Не определено")
        self.current_resolution_display_label.setStyleSheet("font-weight: bold; color: #88eeff;")
        res_display_layout = QHBoxLayout()
        res_display_layout.addStretch()
        res_display_layout.addWidget(self.current_resolution_display_label)
        self.form_layout.addRow(QLabel(""), res_display_layout)

        # Bool параметры
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
            checkbox_layout = QHBoxLayout()
            checkbox_layout.addStretch()
            checkbox_layout.addWidget(checkbox)
            self.config_widgets[param_key] = checkbox
            self.form_layout.addRow(QLabel(display_text), checkbox_layout)

        # DIM_PERCENTAGE
        dim_percentage_label = QLabel("Яркость затемненного (%):")
        dim_percentage_layout = QHBoxLayout()
        self.dim_percentage_slider = QSlider(Qt.Horizontal)
        self.dim_percentage_slider.setRange(0, 100)
        self.dim_percentage_slider.setSingleStep(1)
        # Значение в config_manager — это процент затемнения.
        # Значение на ползунке — это процент яркости.
        initial_dim_percent_val = int(self.current_config.get('DIM_PERCENTAGE', self.DEFAULT_CONFIG['DIM_PERCENTAGE']))
        self.dim_percentage_slider.setValue(100 - initial_dim_percent_val)  # Ползунок показывает 100 - затемнение

        self.dim_percentage_input = QLineEdit(str(self.dim_percentage_slider.value()))
        self.dim_percentage_input.setFixedWidth(50)
        self.dim_percentage_input.setAlignment(Qt.AlignRight)
        self.dim_percentage_input.setValidator(QIntValidator(0, 100))  # Ограничиваем ввод от 0 до 100

        self.dim_percentage_slider.valueChanged.connect(lambda value: self.dim_percentage_input.setText(str(value)))
        self.dim_percentage_input.textChanged.connect(self.update_dim_percentage_slider_from_input)

        dim_percentage_layout.addWidget(self.dim_percentage_slider)
        dim_percentage_layout.addSpacing(10)
        dim_percentage_layout.addWidget(self.dim_percentage_input)
        self.config_widgets['DIM_PERCENTAGE'] = {'slider': self.dim_percentage_slider,
                                                 'input': self.dim_percentage_input}
        self.form_layout.addRow(dim_percentage_label, dim_percentage_layout)

        # CROSS_FADE_DURATION_MS
        cross_fade_duration_label = QLabel("Длительность плавного перехода (мс):")
        self.cross_fade_duration_input = QLineEdit(
            str(self.current_config.get('CROSS_FADE_DURATION_MS', self.DEFAULT_CONFIG['CROSS_FADE_DURATION_MS'])))
        self.cross_fade_duration_input.setAlignment(Qt.AlignRight)
        self.cross_fade_duration_input.setValidator(QIntValidator(0, 2000))  # Ограничиваем ввод от 0 до 2000
        self.config_widgets['CROSS_FADE_DURATION_MS'] = self.cross_fade_duration_input
        self.form_layout.addRow(cross_fade_duration_label, self.cross_fade_duration_input)

        main_layout.addLayout(self.form_layout)

        # Кнопки
        button_layout = QHBoxLayout()
        self.save_message_label = QLabel("", self.content_widget)
        self.save_message_label.setStyleSheet("color: #00ff00; font-weight: bold; margin-right: 10px;")
        self.save_message_label.setMinimumWidth(100)
        self.save_message_label.hide()
        button_layout.addWidget(self.save_message_label)
        button_layout.addStretch()

        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.save_settings)
        button_layout.addWidget(save_button)

        reset_button = QPushButton("Сбросить")
        reset_button.setObjectName("resetButton")
        reset_button.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_button)

        close_button = QPushButton("Закрыть")
        close_button.setObjectName("closeButton")
        # Изменено: теперь просто закрываем окно без лишней логики _trigger_close_via_button
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)

        main_layout.addLayout(button_layout)

        self.setFixedSize(self.sizeHint())
        self.start_pos = None
        self.settings = QSettings("ReactivePlus", "VirtualCameraReactiveSettings")
        self._update_current_resolution_display()  # Обновляем разрешение при инициализации

    def _update_current_resolution_display(self):
        """Обновляет текст в current_resolution_display_label с актуальным разрешением камеры."""
        # Получаем актуальные CAM_WIDTH и CAM_HEIGHT из virtual_camera.py
        # Эти значения обновляются в virtual_camera.initialize_virtual_camera()
        cam_w = virtual_camera.CAM_WIDTH
        cam_h = virtual_camera.CAM_HEIGHT
        if cam_w > 0 and cam_h > 0:
            self.current_resolution_display_label.setText(f"Разрешение камеры: {cam_w}x{cam_h}")
        else:
            self.current_resolution_display_label.setText("Разрешение камеры: Не определено")

    def update_dim_percentage_slider_from_input(self, text):
        """Обновляет ползунок DIM_PERCENTAGE при изменении текста в поле ввода."""
        try:
            value = int(text)
            # Убеждаемся, что значение находится в диапазоне 0-100
            if 0 <= value <= 100:
                self.dim_percentage_slider.setValue(value)
            else:
                # Если введено некорректное значение, возвращаем к текущему значению ползунка
                self.dim_percentage_input.setText(str(self.dim_percentage_slider.value()))
        except ValueError:
            # Если ввод не числовой, возвращаем к текущему значению ползунка
            self.dim_percentage_input.setText(str(self.dim_percentage_slider.value()))

    # Удален _trigger_close_via_button и изменение closeEvent для упрощения,
    # так как теперь окно настроек имеет стандартную кнопку закрытия
    # и не требует специальной обработки для предотвращения случайного закрытия.
    def closeEvent(self, event):
        """Стандартный обработчик события закрытия окна."""
        self.save_window_state()  # Сохраняем положение при закрытии
        event.accept()

    def load_settings_into_gui(self, config_data):
        """Загружает настройки из словаря config_data в виджеты GUI."""
        self.cam_fps_input.setText(str(config_data.get('CAM_FPS', self.DEFAULT_CONFIG['CAM_FPS'])))
        self._update_current_resolution_display()

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

        # Обратное преобразование для DIM_PERCENTAGE: затемнение -> яркость
        initial_dim_percent_val = int(config_data.get('DIM_PERCENTAGE', self.DEFAULT_CONFIG['DIM_PERCENTAGE']))
        self.dim_percentage_slider.setValue(100 - initial_dim_percent_val)
        self.dim_percentage_input.setText(str(100 - initial_dim_percent_val))

        self.cross_fade_duration_input.setText(
            str(config_data.get('CROSS_FADE_DURATION_MS', self.DEFAULT_CONFIG['CROSS_FADE_DURATION_MS'])))

    def reset_settings(self):
        """Сбрасывает все настройки к значениям по умолчанию."""
        self.load_settings_into_gui(self.DEFAULT_CONFIG)
        # Также сохраняем сброшенные настройки в файл
        config_manager.save_config(self.DEFAULT_CONFIG)
        self.current_config = self.DEFAULT_CONFIG.copy()
        # Показываем сообщение о сбросе
        self.save_message_label.setText("Сброшено!")
        self.save_message_label.show()
        QTimer.singleShot(2000, self.save_message_label.hide)

        # Перезапускаем рендерер, чтобы применить сброшенные настройки FPS
        # Добавлено: isinstance(self.parent(), CameraWindow)
        if isinstance(self.parent(), CameraWindow):
            self.parent().restart_renderer()

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
        """Позиционирует окно настроек относительно родительского окна."""
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

        # Логика позиционирования остается прежней
        chosen_x, chosen_y = screen_geo.center().x() - self_rect.width() // 2, screen_geo.center().y() - self_rect.height() // 2

        # Простая реализация позиционирования справа от родителя, если есть место, иначе по центру
        if (parent_rect.right() + self_rect.width() + 10) < screen_geo.right():
            chosen_x = parent_rect.right() + 10
            chosen_y = y_aligned_with_parent
        elif (parent_rect.left() - self_rect.width() - 10) > screen_geo.left():
            chosen_x = parent_rect.left() - self_rect.width() - 10
            chosen_y = y_aligned_with_parent
        # Если нет места по бокам, центрируем

        self.move(chosen_x, chosen_y)

    def mousePressEvent(self, event):
        """Начало перетаскивания окна."""
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
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

    def save_settings(self):
        """Сохраняет текущие настройки из GUI-элементов в config.txt."""
        new_config_data = self.current_config.copy()
        old_cam_fps = int(new_config_data.get('CAM_FPS', self.DEFAULT_CONFIG['CAM_FPS']))

        try:
            new_cam_fps = int(self.cam_fps_input.text())
            if new_cam_fps <= 0:
                raise ValueError("FPS должен быть положительным числом.")
            new_config_data['CAM_FPS'] = str(new_cam_fps)
        except ValueError as e:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Ошибка ввода")
            msg_box.setText(f"Неверное значение для FPS: {e}")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setStyleSheet(
                "QMessageBox { background-color: #1a1a1a; color: #ffffff; } QLabel { color: #ffffff; } QPushButton { background-color: #007bff; color: #ffffff; border-radius: 5px; padding: 5px 10px; } QPushButton:hover { background-color: #0056b3; }")
            msg_box.exec_()
            return

        bool_params_map = {
            'CROSS_FADE_ENABLED': 'Включить плавный переход:',
            'BOUNCING_ENABLED': 'Включить эффект "подпрыгивания":',
            'RESET_ANIMATION_ON_STATUS_CHANGE': 'Сбрасывать анимацию при смене статуса:',
            'INSTANT_TALK_TRANSITION': 'Мгновенный переход в статус "Говорит":',
            'DIM_ENABLED': 'Включить затемнение при молчании:'
        }
        for param_key in bool_params_map:
            checkbox = self.config_widgets[param_key]
            new_config_data[param_key] = str(checkbox.isChecked())

        try:
            brightness_value = int(self.dim_percentage_input.text())
            if not (0 <= brightness_value <= 100):
                raise ValueError("Яркость затемненного должна быть от 0 до 100.")
            # Сохраняем как процент затемнения (100 - яркость)
            new_config_data['DIM_PERCENTAGE'] = str(100 - brightness_value)
        except ValueError as e:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Ошибка ввода")
            msg_box.setText(f"Неверное значение для яркости затемненного: {e}")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setStyleSheet(
                "QMessageBox { background-color: #1a1a1a; color: #ffffff; } QLabel { color: #ffffff; } QPushButton { background-color: #007bff; color: #ffffff; border-radius: 5px; padding: 5px 10px; } QPushButton:hover { background-color: #0056b3; }")
            msg_box.exec_()
            return

        try:
            new_fade_duration = int(self.cross_fade_duration_input.text())
            if new_fade_duration < 0:
                raise ValueError("Длительность перехода не может быть отрицательной.")
            new_config_data['CROSS_FADE_DURATION_MS'] = str(new_fade_duration)
        except ValueError as e:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Ошибка ввода")
            msg_box.setText(f"Неверное значение для длительности перехода: {e}")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setStyleSheet(
                "QMessageBox { background-color: #1a1a1a; color: #ffffff; } QLabel { color: #ffffff; } QPushButton { background-color: #007bff; color: #ffffff; border-radius: 5px; padding: 5px 10px; } QPushButton:hover { background-color: #0056b3; }")
            msg_box.exec_()
            return

        config_manager.save_config(new_config_data)
        self.current_config = new_config_data

        self.save_message_label.setText("Сохранено!")
        self.save_message_label.show()
        QTimer.singleShot(2000, self.save_message_label.hide)

        # Проверяем, изменились ли параметры, влияющие на рендерер, и сообщаем главному окну
        camera_params_changed = (str(old_cam_fps) != new_config_data['CAM_FPS'])
        if camera_params_changed:
            print("Параметры камеры (FPS) изменились. Перезапускаю рендерер...")
            if isinstance(self.parent(), CameraWindow):
                self.parent().restart_renderer()  # Вызываем метод перезапуска рендерера в CameraWindow
            print("Рендерер перезапущен с новыми параметрами.")
        else:
            # Обновляем параметры в renderer без полного перезапуска, если изменились только визульные
            if isinstance(self.parent(), CameraWindow):
                self.parent().renderer.load_config_and_assets()  # Обновляем конфиг в рендерере
                # Имитируем обновление статуса, чтобы рендерер применил новые визуальные настройки
                # Передаем текущий статус, который хранится в self.parent().status_monitor._current_voice_status
                self.parent().renderer.on_status_changed(self.parent().status_monitor._current_voice_status,
                                                         "[GUI] Обновление визуальных настроек.")
            print("Настройки обновлены. Рендерер не перезапускался, но его конфиг обновлен.")


class CustomTitleBar(QWidget):
    """Кастомная полоса заголовка для окна."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.start_pos = None
        self.settings_window = None
        self.maximized = False

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#1a1a1a"))
        self.setPalette(palette)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("""
            QWidget { background-color: #1a1a1a; color: #ffffff; font-family: "Segoe UI", sans-serif; font-size: 12px; border-top-left-radius: 12px; border-top-right-radius: 12px; }
            QLabel { font-family: "Segoe UI", sans-serif; font-size: 11px; font-weight: bold; }
            QPushButton { background-color: transparent; color: #ffffff; border: none; padding: 5px 10px; margin: 0px; min-width: 30px; font-weight: bold; border-radius: 0px; font-family: "Segoe UI", "Arial", sans-serif; font-size: 14px; }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); }
            QPushButton#closeButton:hover { background-color: #e81123; }
            QPushButton#quitButton { border-top-right-radius: 10px; }
            QPushButton#quitButton:hover { background-color: #e81123; }
        """)
        self.setFixedHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        self.icon_label = QLabel(self)
        if os.path.exists(ICON_PATH):
            pixmap = QPixmap(ICON_PATH).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pixmap)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(WINDOW_TITLE, self)
        layout.addWidget(self.title_label)
        layout.addStretch()

        # --- ВОССТАНОВЛЕННЫЕ КНОПКИ ---
        self.settings_button = QPushButton("⚙", self)
        self.settings_button.clicked.connect(self.open_settings_window)
        self.settings_button.setToolTip("Настройки")
        layout.addWidget(self.settings_button)

        self.minimize_button = QPushButton("—", self)
        self.minimize_button.clicked.connect(self.parent_window.showMinimized)
        self.minimize_button.setToolTip("Свернуть")
        layout.addWidget(self.minimize_button)

        self.maximize_restore_button = QPushButton("☐", self)  # Добавлена кнопка максимизации
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
            # Передаем родительское окно в качестве родителя SettingsWindow
            self.settings_window = SettingsWindow(self.parent_window)
            self.settings_window.setAttribute(Qt.WA_DeleteOnClose)  # Удалять при закрытии

        self.settings_window.current_config = config_manager.load_config()
        self.settings_window.load_settings_into_gui(self.settings_window.current_config)
        self.settings_window._update_current_resolution_display()

        if self.settings_window.isVisible():
            self.settings_window.hide()
            self.settings_window.save_window_state()  # Сохраняем положение при скрытии
        else:
            self.settings_window.load_window_state()  # Загружаем положение при показе
            # Позиционируем относительно родительского окна, если оно видимо
            if not self.parent_window.isHidden() and not self.parent_window.isMinimized():
                self.settings_window.position_relative_to_parent()

            self.settings_window.show()
            self.settings_window.activateWindow()
            self.settings_window.raise_()

    def toggle_maximize_restore(self):
        """Переключает состояние окна между максимизированным и нормальным."""
        if self.maximized:
            self.parent_window.showNormal()
            self.maximized = False
            self.maximize_restore_button.setText("☐")
            self.maximize_restore_button.setToolTip("Развернуть")
            # Восстанавливаем фиксированный размер VGA
            self.parent_window.setFixedSize(self.parent_window.calculate_target_geometry(VGA_WIDTH, VGA_HEIGHT))
        else:
            self.parent_window.showMaximized()
            self.maximized = True
            self.maximize_restore_button.setText("🗗")
            self.maximize_restore_button.setToolTip("Восстановить")
            # Убираем фиксированный размер при максимизации
            self.parent_window.setMinimumSize(0, 0)
            self.parent_window.setMaximumSize(16777215, 16777215)
        self.parent_window._update_main_container_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.globalPos() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.start_pos is not None:
            if not self.maximized:  # Перетаскивать только если не максимизировано
                self.parent_window.move(event.globalPos() - self.start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.start_pos = None
        event.accept()


class AnimatedMenu(QMenu):
    """Кастомное QMenu, которое появляется и исчезает с анимацией прозрачности."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.opacity_animation.setDuration(200)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutQuad)
        self.aboutToHide.connect(self._start_fade_out)

        # Установка стилей для меню трея (восстановлены из gui_elements_old)
        self.setStyleSheet("""
            QMenu {
                background-color: rgba(51, 51, 51, 0.98); /* Почти непрозрачный темный фон */
                border: 1px solid #666666;
                border-radius: 5px;
                color: #ffffff;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                background-color: transparent;
                padding: 6px 15px;
                border-radius: 0px;
                margin: 0px;
            }
            QMenu::item:selected {
                background-color: #007acc; /* Цвет выделения */
                color: #ffffff;
                border-radius: 3px;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(100, 100, 100, 0.7);
                margin-left: 10px;
                margin-right: 10px;
            }
        """)

    def popup(self, pos, action=None):
        """Переопределяем метод popup для запуска анимации появления."""
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
        """Запускает анимацию скрытия меню."""
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
        """Скрывает меню после завершения анимации исчезновения."""
        try:
            self.opacity_animation.finished.disconnect(self._actual_hide)
        except TypeError:
            pass
        self.hide()


class CameraWindow(QWidget):
    """Главное окно приложения."""
    update_image_signal = pyqtSignal(np.ndarray)
    restart_renderer_signal = pyqtSignal()

    def __init__(self, status_monitor):
        super().__init__()
        self.status_monitor = status_monitor
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")

        if os.path.exists(ICON_PATH): self.setWindowIcon(QIcon(ICON_PATH))

        self.display_queue = queue.Queue(maxsize=2)
        # Инициализируем рендерер здесь, передавая ему очередь
        self.renderer = Renderer(self.display_queue)

        main_window_layout = QVBoxLayout(self)
        main_window_layout.setContentsMargins(0, 0, 0, 0)
        main_window_layout.setSpacing(0)
        self.main_container_widget = QWidget(self)
        self.main_container_widget.setStyleSheet("background-color: #1a1a1a; border-radius: 12px;")
        main_container_layout = QVBoxLayout(self.main_container_widget)
        main_container_layout.setContentsMargins(0, 0, 0, 0)
        main_container_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        main_container_layout.addWidget(self.title_bar)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)  # Добавлены отступы
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; border-radius: 8px;")
        content_layout.addWidget(self.image_label)
        main_container_layout.addWidget(content_widget)

        main_window_layout.addWidget(self.main_container_widget)

        # Устанавливаем начальный размер окна, используя функцию calculate_target_geometry
        initial_window_size = self.calculate_target_geometry(VGA_WIDTH, VGA_HEIGHT)
        self.setFixedSize(initial_window_size)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(ICON_PATH))
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_menu = AnimatedMenu(self)  # Используем AnimatedMenu

        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self.show_window)
        self.tray_menu.addAction(show_action)

        settings_action = QAction("Настройки", self)  # Действие для открытия окна настроек
        settings_action.triggered.connect(lambda: self.title_bar.open_settings_window())
        self.tray_menu.addAction(settings_action)

        self.tray_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(quit_action)
        self.tray_icon.show()

        # Таймер для предпросмотра
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.check_for_new_frame)

        self.update_image_signal.connect(self.update_image_on_gui_thread)
        self.restart_renderer_signal.connect(self.restart_renderer)

        # Подключаем сигнал статуса монитора к слоту рендерера
        self.status_monitor.status_changed.connect(self.renderer.on_status_changed)

        self.settings = QSettings("ReactivePlus", "VirtualCameraReactive")
        self.load_window_state()
        self._update_main_container_style()  # Обновляем стиль контейнера при запуске

        # Обновляем демо-изображение после инициализации и загрузки всех ресурсов
        # Важно убедиться, что рендерер загрузил ассеты до этого вызова
        self._current_cv_frame = None  # Инициализируем для хранения последнего кадра
        self._update_demo_image_with_status_circle()

        # Анимация появления окна
        self.opacity_animation = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_animation.setDuration(200)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutQuad)

    def start_app_processes(self):
        """Запускает рендеринг и таймер предпросмотра, показывает окно."""
        self.renderer.start_rendering()
        # Запускаем таймер предпросмотра с FPS из рендерера
        fps = self.renderer.cam_fps
        self.preview_timer.start(1000 // fps if fps > 0 else 33)

        # Показываем окно и запускаем анимацию появления
        self.show()
        self.opacity_animation.start()

    def check_for_new_frame(self):
        """Проверяет очередь на наличие новых кадров из виртуальной камеры и отправляет их в GUI."""
        try:
            frame_rgb = self.display_queue.get_nowait()
            self.update_image_signal.emit(frame_rgb)
        except queue.Empty:
            pass

    @pyqtSlot(np.ndarray)
    def update_image_on_gui_thread(self, frame_rgb):
        """Обновляет изображение в QLabel в GUI-потоке."""
        if frame_rgb is None: return
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w

        # Используем .data для получения указателя на буфер numpy
        # .copy() в конце QImage() гарантирует, что QImage создаст свою собственную копию данных
        # Это предотвращает BufferError при закрытии, если numpy массив будет освобожден позже
        qt_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qt_image)
        self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._current_cv_frame = frame_rgb  # Сохраняем ссылку на текущий кадр

    def restart_renderer(self):
        """Перезапускает рендерер и его таймер после изменения настроек."""
        print("GUI: Перезапуск рендерера...")
        self.renderer.stop_rendering()
        self.renderer.load_config_and_assets()  # Перезагружаем конфиг и ассеты в рендерере
        self.renderer.start_rendering()

        # Обновляем FPS таймера предпросмотра в соответствии с новым конфигом
        fps = self.renderer.cam_fps
        self.preview_timer.stop()  # Останавливаем, чтобы перезапустить с новым интервалом
        self.preview_timer.start(1000 // fps if fps > 0 else 33)
        print("GUI: Рендерер успешно перезапущен.")

        # Обновляем демонстрационное изображение, чтобы показать новый статус/разрешение
        self._update_demo_image_with_status_circle()

    def closeEvent(self, event):
        """Обработчик события закрытия окна (сворачивание в трей)."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("minimizedToTray", True)
        self.hide()
        self.tray_icon.showMessage(
            WINDOW_TITLE,
            "Приложение свернуто в системный трей.",
            QSystemTrayIcon.Information,
            2000
        )
        event.ignore()

    def quit_app(self):
        """Полностью закрывает приложение и освобождает ресурсы."""
        print("GUI: Запрос на полное завершение приложения...")
        # Явно удаляем ссылки на numpy массивы, связанные с общей памятью
        if self._current_cv_frame is not None:
            del self._current_cv_frame
            self._current_cv_frame = None

        # Опустошаем очередь, чтобы не было висячих ссылок
        while not self.display_queue.empty():
            try:
                item = self.display_queue.get_nowait()
                del item  # Явно удаляем каждый элемент
            except queue.Empty:
                break

        # Очистка ресурсов рендерера
        self.renderer.cleanup()

        # Скрываем иконку трея и выходим из приложения
        self.tray_icon.hide()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("minimizedToTray", False)  # Сбрасываем флаг, если выходим полностью
        QApplication.instance().quit()

    def show_window(self):
        """Показывает окно приложения."""
        self.show()
        self.activateWindow()
        self.raise_()
        # Запускаем анимацию появления окна, если оно было скрыто
        if self.windowOpacity() < 1.0:
            self.opacity_animation.start()

    def tray_activated(self, reason):
        """Обработчик события активации иконки в трее."""
        if reason == QSystemTrayIcon.Trigger:  # Левый клик
            self.show_window()
        elif reason == QSystemTrayIcon.Context:  # Правый клик
            self.tray_menu.popup(QCursor.pos())

    def load_window_state(self):
        """Загружает сохраненное положение окна и состояние из QSettings."""
        minimized_to_tray = self.settings.value("minimizedToTray", False, type=bool)
        if minimized_to_tray:
            self.hide()
            # Показываем сообщение только если приложение не запускается впервые с этим флагом
            # или если пользователь не вышел полностью в прошлый раз
            print("Приложение было свернуто в трей при последнем запуске.")
            QTimer.singleShot(500, lambda: self.tray_icon.showMessage(
                WINDOW_TITLE,
                "Приложение было свернуто в трей при последнем запуске.",
                QSystemTrayIcon.Information,
                2000
            ))
            return

        geometry_data = self.settings.value("geometry")
        if geometry_data:
            self.restoreGeometry(geometry_data)
            # Проверяем, находится ли окно на экране
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

        self.setWindowOpacity(0.0)  # Начальная прозрачность для анимации

    def move_to_active_screen_center(self):
        """Перемещает окно в центр экрана, где находится курсор мыши."""
        current_screen = QApplication.screenAt(QCursor.pos())
        if current_screen is None:
            current_screen = QApplication.primaryScreen()
        screen_geo = current_screen.availableGeometry()
        screen_center_x = screen_geo.center().x()
        screen_center_y = screen_geo.center().y()
        current_size = self.size()
        target_x = screen_center_x - (current_size.width() // 2)
        target_y = screen_center_y - (current_size.height() // 2)
        self.setGeometry(target_x, target_y, current_size.width(), current_size.height())

    def _update_main_container_style(self):
        """Обновляет стиль main_container_widget в зависимости от состояния окна."""
        if self.isMaximized():
            self.main_container_widget.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border-radius: 0px;
                }
            """)
        else:
            self.main_container_widget.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border-radius: 12px;
                }
            """)

    def calculate_target_geometry(self, content_width, content_height):
        """Рассчитывает целевую геометрию окна на основе заданных размеров контента."""
        # Активируем макеты для корректного расчета размеров
        self.layout().activate()
        self.main_container_widget.layout().activate()
        # Убедимся, что self.title_bar уже создан и имеет высоту
        title_bar_height = self.title_bar.height() if hasattr(self, 'title_bar') else 0

        # Получаем отступы из content_layout
        content_layout = self.main_container_widget.findChild(QVBoxLayout)
        if content_layout and content_layout.parentWidget() == self.main_container_widget:
            # Ищем layout, который содержит image_label, чтобы получить его отступы
            # В текущей структуре content_inner_widget (у нас content_widget) содержит image_label
            inner_content_layout = self.main_container_widget.layout().itemAt(1).widget().layout()  # Это content_layout
            if inner_content_layout:
                fixed_height_for_margins = title_bar_height + \
                                           inner_content_layout.contentsMargins().top() + \
                                           inner_content_layout.contentsMargins().bottom()
                fixed_width_for_margins = inner_content_layout.contentsMargins().left() + \
                                          inner_content_layout.contentsMargins().right()

                total_height = content_height + fixed_height_for_margins
                total_width = content_width + fixed_width_for_margins
                return QSize(total_width, total_height)

        # Запасной вариант, если макеты еще не полностью настроены
        # Или если структура макетов изменится
        # Используем фиксированные 30 для title_bar и 10 для отступов сверху/снизу
        total_height = content_height + (self.title_bar.height() if hasattr(self, 'title_bar') else 30) + 10
        total_width = content_width + 10  # 5px слева + 5px справа
        return QSize(total_width, total_height)

    def resizeEvent(self, event):
        """Обработчик события изменения размера окна."""
        super().resizeEvent(event)
        # При изменении размера окна, если есть кадр, масштабируем его под image_label
        if self._current_cv_frame is not None:
            self.update_image_on_gui_thread(self._current_cv_frame)

    def _update_demo_image_with_status_circle(self):
        """Генерирует демонстрационное изображение для окна предварительного просмотра."""
        cam_w = self.renderer.cam_width  # Используем ширину из рендерера
        cam_h = self.renderer.cam_height  # Используем высоту из рендерера

        if cam_w == 0 or cam_h == 0:
            # Если рендерер еще не загрузил фон, используем значения по умолчанию
            cam_w = virtual_camera.CAM_WIDTH
            cam_h = virtual_camera.CAM_HEIGHT
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: Размеры CAM_WIDTH/CAM_HEIGHT в renderer.py не определены при обновлении демонстрационного изображения. Использую {cam_w}x{cam_h} из virtual_camera.")

        # Создаем заглушку изображения в соответствии с новыми размерами
        # Для демонстрационной картинки используем RGB для простоты
        preview_frame_rgb = np.zeros((cam_h, cam_w, 3), dtype=np.uint8)

        # Добавляем круги статуса как в старой версии, чтобы показать текущий статус
        status = self.status_monitor._current_voice_status
        center_x, center_y = cam_w // 2, cam_h // 2
        radius = min(cam_w, cam_h) // 4

        if status == "Говорит":
            color = (0, 255, 0)  # Зеленый
            text = "ГОВОРИТ"
        elif status == "Микрофон выключен (muted)":
            color = (255, 0, 0)  # Красный
            text = "Muted"
        elif status == "Полностью заглушен (deafened)":
            color = (0, 0, 255)  # Синий
            text = "Deafened"
        else:  # Молчит или другие состояния
            color = (100, 100, 100)  # Серый
            text = "Молчит"

        # Убедимся, что OpenCV цвета в формате BGR
        cv2.circle(preview_frame_rgb, (center_x, center_y), radius, (color[2], color[1], color[0]), -1)  # Передаем BGR
        # Добавляем текст
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = min(cam_w, cam_h) / 600.0  # Масштабируем шрифт
        thickness = max(1, int(font_scale * 2))
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        text_x = center_x - text_size[0] // 2
        text_y = center_y + text_size[1] // 2
        cv2.putText(preview_frame_rgb, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness,
                    cv2.LINE_AA)

        self.update_image_signal.emit(preview_frame_rgb)

    # --- Добавленный метод для обработки изменения состояния окна ---
    def changeEvent(self, event):
        """
        Обрабатывает изменения состояния окна.
        Мы будем останавливать обновление предпросмотра, когда окно свернуто.
        """
        if event.type() == Qt.Event.WindowStateChange:
            if self.isMinimized():
                print("[GUI] Окно свернуто. Остановка таймера предпросмотра.")
                self.preview_timer.stop()  # Останавливаем таймер предпросмотра
            else:  # Если окно развернуто (восстановлено из свернутого, максимизировано или в нормальном состоянии)
                print("[GUI] Окно развернуто. Запуск таймера предпросмотра.")
                # Запускаем таймер только если он не активен
                if not self.preview_timer.isActive():
                    fps = self.renderer.cam_fps  # Используем актуальный FPS рендерера
                    self.preview_timer.start(1000 // fps if fps > 0 else 33)
                # Если окно только что развернуто, обновим демо-изображение
                self._update_demo_image_with_status_circle()

        super().changeEvent(event)  # Важно вызвать родительский метод


class CustomStatusHandler(QObject):
    status_display_signal = pyqtSignal(str, str)

    def __init__(self, gui_status_callback):
        super().__init__()
        self.status_display_signal.connect(gui_status_callback, Qt.QueuedConnection)

    def on_status_change(self, status_message: str, debug_message: str):
        """Этот метод вызывается из потока Playwright."""
        self.status_display_signal.emit(status_message, debug_message)


def create_placeholder_images_for_gui():
    """Создает заглушки изображений для GUI и трея, если они отсутствуют.
       Использует Pillow для сохранения PNG, чтобы избежать ошибок OpenCV.
       Эта функция должна быть вызвана до того, как Renderer или CameraWindow
       попытаются загрузить ассеты, чтобы гарантировать их наличие.
    """
    # Этот импорт нужен только здесь, чтобы не создавать циклический импорт
    # или зависимости на верхнем уровне модуля.
    # Если virtual_camera.AVATAR_ASSETS_FOLDER нужен на верхнем уровне,
    # то это проблема архитектуры.
    # Сейчас, я просто переопределяю его локально, чтобы не сломать зависимости.
    # Также, в virtual_camera.py у нас нет AVATAR_ASSETS_FOLDER,
    # поэтому используем путь из renderer.py, но чтобы избежать конфликтов/зависимостей,
    # я просто использую SCRIPT_DIR + reactive_avatar.
    # В идеале, эта папка должна быть централизованно определена.

    avatar_assets_folder = os.path.join(SCRIPT_DIR, "reactive_avatar")
    os.makedirs(avatar_assets_folder, exist_ok=True)

    # Вспомогательная функция для сохранения NumPy массива в PNG с Pillow
    def save_np_array_as_png(np_array, path):
        # OpenCV обычно работает с BGR, а Pillow с RGB.
        # Если np_array создан OpenCV (BGR), нужно конвертировать в RGB для Pillow.
        # Если он уже RGB (как в демо-кадрах GUI), то не нужно.
        # Здесь предполагается, что вход - это уже RGBA (как для иконок)
        # или RGB (как для демонстрационных кругов)
        if np_array.shape[-1] == 4:  # RGBA
            img_pil = Image.fromarray(np_array, 'RGBA')
        elif np_array.shape[-1] == 3:  # RGB
            img_pil = Image.fromarray(np_array, 'RGB')
        else:
            raise ValueError("Неподдерживаемый формат массива для сохранения PNG")
        img_pil.save(path, format="PNG")

    # Создаем app_icon.png
    if not os.path.exists(ICON_PATH):
        print(f"  Создаю заглушку '{os.path.basename(ICON_PATH)}'.")
        icon_size = 64
        # Используем RGBA для поддержки прозрачности, как в иконках
        placeholder_icon = np.zeros((icon_size, icon_size, 4), dtype=np.uint8)  # Черный фон с альфой
        # OpenCV цвета в BGR формате
        cv2.circle(placeholder_icon, (icon_size // 2, icon_size // 2), icon_size // 2 - 5, (0, 165, 255, 255),
                   -1)  # Оранжевый круг (BGR)
        # Текст
        cv2.putText(placeholder_icon, "VC", (icon_size // 2 - 15, icon_size // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_icon, ICON_PATH)

    # Создаем BG.png - заглушка для определения размера CAM_WIDTH/HEIGHT
    # Используем путь из Renderer, а не из virtual_camera, т.к. virtual_camera не должен знать про пути ассетов
    bg_path = os.path.join(avatar_assets_folder,
                           f"{Renderer.BACKGROUND_IMAGE_BASENAME}.png")  # Используем Renderer.BACKGROUND_IMAGE_BASENAME
    if not os.path.exists(bg_path):
        print(f"  Создаю заглушку '{os.path.basename(bg_path)}'.")
        # Используем стандартный размер 640x360 для заглушки фона
        placeholder_bg = np.full((360, 640, 3), 150, dtype=np.uint8)  # Серое 640x360 (RGB)
        save_np_array_as_png(placeholder_bg, bg_path)

    # Создаем Speaking.png
    speaking_path = os.path.join(avatar_assets_folder, f"{Renderer.STATUS_TO_FILENAME_MAP['Говорит']}.png")
    if not os.path.exists(speaking_path):
        print(f"  Создаю заглушку '{os.path.basename(speaking_path)}'.")
        avatar_size = 200
        placeholder_avatar = np.zeros((avatar_size, avatar_size, 4), dtype=np.uint8)  # RGBA
        center = (avatar_size // 2, avatar_size // 2)
        radius = avatar_size // 2 - 10
        cv2.circle(placeholder_avatar, center, radius, (0, 255, 0, 255), -1)  # Зеленый круг (BGR), альфа 255
        cv2.putText(placeholder_avatar, "Speaking", (center[0] - 60, center[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_avatar, speaking_path)

    # Создаем Inactive.png
    inactive_path = os.path.join(avatar_assets_folder, f"{Renderer.STATUS_TO_FILENAME_MAP['Молчит']}.png")
    if not os.path.exists(inactive_path):
        print(f"  Создаю заглушку '{os.path.basename(inactive_path)}'.")
        # Попробуем загрузить Speaking.png, затемнить и сохранить
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
            print(f"Ошибка при создании Inactive.png из Speaking.png: {e}. Создаю простую серую заглушку.")
            # Fallback: Если не удалось, создаем простую серую заглушку
            placeholder_inactive = np.zeros((200, 200, 4), dtype=np.uint8)  # RGBA
            cv2.circle(placeholder_inactive, (100, 100), 90, (100, 100, 100, 255), -1)  # Серый круг (BGR)
            cv2.putText(placeholder_inactive, "Inactive", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
            save_np_array_as_png(placeholder_inactive, inactive_path)

    # Создаем Muted.png (Микрофон выключен) - КРАСНЫЙ
    muted_path = os.path.join(avatar_assets_folder,
                              f"{Renderer.STATUS_TO_FILENAME_MAP['Микрофон выключен (muted)']}.png")
    if not os.path.exists(muted_path):
        print(f"  Создаю заглушку '{os.path.basename(muted_path)}'.")
        placeholder_muted = np.zeros((200, 200, 4), dtype=np.uint8)  # RGBA
        cv2.circle(placeholder_muted, (100, 100), 90, (0, 0, 200, 255), -1)  # Ярко-красный круг (BGR)
        cv2.putText(placeholder_muted, "Muted", (60, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_muted, muted_path)

    # Создаем Deafened.png (Полностью заглушен) - СИНИЙ
    deafened_path = os.path.join(avatar_assets_folder,
                                 f"{Renderer.STATUS_TO_FILENAME_MAP['Полностью заглушен (deafened)']}.png")
    if not os.path.exists(deafened_path):
        print(f"  Создаю заглушку '{os.path.basename(deafened_path)}'.")
        placeholder_deafened = np.zeros((200, 200, 4), dtype=np.uint8)  # RGBA
        cv2.circle(placeholder_deafened, (100, 100), 90, (200, 0, 0, 255), -1)  # Ярко-синий круг (BGR)
        cv2.putText(placeholder_deafened, "Deafened", (40, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0, 255), 2)
        save_np_array_as_png(placeholder_deafened, deafened_path)

    print("Проверка заглушек изображений завершена.")


def start_gui(voice_monitor_instance):  # Принимаем экземпляр монитора
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setQuitOnLastWindowClosed(False)

    window = CameraWindow(voice_monitor_instance)  # Передаем экземпляр монитора в CameraWindow
    window.start_app_processes()  # Запускаем рендерер и таймер

    sys.exit(app.exec_())


if __name__ == '__main__':
    # Эта часть больше не должна выполняться напрямую,
    # так как запуск GUI теперь происходит из main_script.py
    # Если запустить напрямую, voice_monitor_instance не будет передан.
    # В реальном приложении этот блок лучше убрать или оставить для отладки GUI.

    # Для целей отладки, если этот файл запускается сам по себе:
    # Инициализация заглушек
    # from reactive_monitor import VoiceMonitor
    # create_placeholder_images_for_gui()
    # dummy_monitor = VoiceMonitor(profile_dir="temp_profile", ADD_PIXEL_MUTED_COLOR=[0,0,0,0], ADD_PIXEL_DEAFENED_COLOR=[0,0,0,0], PIXEL_CHECK_X=0, PIXEL_CHECK_Y=0, ADD_PIXEL_PROTECTION_COLOR=[0,0,0,0], DIM_PERCENTAGE=0)
    # start_gui(dummy_monitor)
    pass
