import asyncio
import os
import sys
import threading
from playwright.async_api import async_playwright, Playwright
from PyQt5.QtWidgets import QApplication

# Импортируем наши собственные модули
import config_manager
import image_processor
import reactive_login_flow
import reactive_model_manager
from reactive_monitor import VoiceMonitor  # Импортируем новый класс VoiceMonitor
from gui_elements import CameraWindow
import logging_manager

# --- CONFIGURATION ---
# (Эти константы остаются без изменений)
ADD_PIXEL_MUTED_COLOR = [255, 0, 0, 255]
ADD_PIXEL_DEAFENED_COLOR = [0, 0, 255, 255]
ADD_PIXEL_PROTECTION_COLOR = [0, 0, 0, 255]
DIM_PERCENTAGE = 50
PIXEL_CHECK_X = 0
PIXEL_CHECK_Y = 0

def run_background_tasks(monitor_instance):
    """
    Создает новый цикл событий для фонового потока и запускает монитор.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(monitor_instance.run())
    loop.close()


if __name__ == "__main__":
    # 1. Настраиваем логирование
    logging_manager.setup_logging()
    sys.excepthook = logging_manager.handle_exception

    # 2. Создаем экземпляр QApplication *ДО* создания любых виджетов
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 3. Определяем путь к профилю Playwright
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    persistent_profile_dir = os.path.join(SCRIPT_DIR, "playwright_profile")
    os.makedirs(persistent_profile_dir, exist_ok=True)

    # 4. Создаем экземпляр монитора
    # Этот объект будет жить в основном потоке, но его метод run() будет вызван в другом
    voice_monitor = VoiceMonitor(
        persistent_profile_dir,
        ADD_PIXEL_MUTED_COLOR=ADD_PIXEL_MUTED_COLOR,
        ADD_PIXEL_DEAFENED_COLOR=ADD_PIXEL_DEAFENED_COLOR,
        PIXEL_CHECK_X=PIXEL_CHECK_X,
        PIXEL_CHECK_Y=PIXEL_CHECK_Y,
        ADD_PIXEL_PROTECTION_COLOR=ADD_PIXEL_PROTECTION_COLOR,
        DIM_PERCENTAGE=DIM_PERCENTAGE
    )

    # 5. Создаем главное окно GUI и передаем ему монитор
    # Это позволяет окну подключить свои слоты к сигналам монитора
    main_window = CameraWindow(voice_monitor)

    # 6. Создаем и запускаем фоновый поток для Playwright и мониторинга
    background_thread = threading.Thread(
        target=run_background_tasks,
        args=(voice_monitor,),
        name="BackgroundPlaywrightThread"
    )
    background_thread.daemon = True
    background_thread.start()

    # 7. Запускаем рендеринг и показываем окно
    # Этот метод теперь отвечает за запуск таймеров и отображение окна
    main_window.start_app_processes()

    # 8. Запускаем цикл событий Qt
    sys.exit(app.exec_())
