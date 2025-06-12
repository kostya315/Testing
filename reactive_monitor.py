import asyncio
import sys
from playwright.async_api import Playwright, Page, BrowserContext

# --- КОНФИГУРАЦИЯ ---
LOGIN_URL = "https://reactive.fugi.tech/"  # Это должно быть импортировано из config_manager или main_script
POLLING_INTERVAL_SECONDS = 0.05  # Интервал проверки статуса в секундах (50 миллисекунд)
PIXEL_COLOR_TOLERANCE = 5  # Допуск для сравнения цветов пикселей (для каждого канала R, G, B, A)

# Цвета, используемые при ПРОВЕРКЕ пикселя на странице individual
CHECK_PIXEL_MUTED_COLOR = [127, 0, 0, 255]  # Ожидаемый красный для состояния "Микрофон выключен (muted)"
CHECK_PIXEL_DEAFENED_COLOR = [0, 0, 127, 255]  # Ожидаемый синий для состояния "Полностью заглушен (deafened)"
# Особый случай: черный цвет пикселя (0,0,0,0) может означать, что картинка еще не прогрузилась
PIXEL_LOADING_COLOR = [0, 0, 0, 0]

# Координаты пикселя для проверки
PIXEL_CHECK_X = 0
PIXEL_CHECK_Y = 0

# --- Глобальная переменная для статуса голоса ---
_current_voice_status = None  # Будет хранить текущий статус голоса, инициализируется при первом запуске монитора


def are_colors_approximately_equal(color1: tuple, color2: tuple, tolerance: int = 5) -> bool:
    """
    Checks if two RGBA colors are approximately equal within a given tolerance.
    Tolerance is the maximum allowed difference for each channel.
    """
    if not isinstance(color1, (list, tuple)) or not isinstance(color2, (list, tuple)) or \
            len(color1) != 4 or len(color2) != 4:
        return False

    for i in range(4):  # R, G, B, A channels
        if not (color2[i] - tolerance <= color1[i] <= color2[i] + tolerance):
            return False
    return True


async def monitor_voice_status(p: Playwright, user_id: str, profile_dir: str, status_change_callback):
    """
    Мониторит статус голоса пользователя на странице OBS-источника.
    Отслеживает 'data-speaking' и цвета пикселей на канвасе для 'muted'/'deafened'.
    Запускает свой собственный безголовый браузер.
    status_change_callback: Функция, которая будет вызвана при изменении статуса.
                            Принимает (status_message: str, debug_message: str)
    """
    global _current_voice_status  # Указываем, что будем использовать глобальную переменную

    individual_obs_url = f"{LOGIN_URL}individual/{user_id}"
    print(f"\nМониторинг статуса голоса на: {individual_obs_url}")

    obs_browser_context: BrowserContext = None
    obs_page: Page = None
    try:
        # Запускаем новый постоянный контекст для мониторинга, безголовый
        obs_browser_context = await p.chromium.launch_persistent_context(
            profile_dir,
            channel='msedge',  # Используем msedge, если доступен
            headless=True  # Запускаем в безголовом режиме для мониторинга
        )
        obs_page = await obs_browser_context.new_page()
        await obs_page.goto(individual_obs_url)
        await obs_page.wait_for_load_state('domcontentloaded')

        print("Запущен мониторинг голоса. Статус будет обновляться при изменении.")
        print(f"Ожидаемые цвета пикселя ({PIXEL_CHECK_X},{PIXEL_CHECK_Y}) для определения состояния заглушения:")
        print(f"  Микрофон выключен (muted): {CHECK_PIXEL_MUTED_COLOR}")
        print(f"  Полностью заглушен (deafened): {CHECK_PIXEL_DEAFENED_COLOR}")

        # Инициализируем статус при первом запуске
        _current_voice_status = "Инициализация..."  # Начальный статус, который будет обновлен
        # Здесь не выводим статус в консоль напрямую, это будет делать callback

        while True:
            try:
                js_get_full_state_function = f"""() => {{
                    const element = document.querySelector('div[data-discord-id="{user_id}"][data-speaking]');
                    if (!element) {{
                        return {{ speaking: null, pixel_color: null }};
                    }}

                    const speaking = element.getAttribute('data-speaking') === 'true';

                    const canvas = element.querySelector('canvas');
                    let pixelColor = null;

                    if (canvas && canvas.width > {PIXEL_CHECK_X} && canvas.height > {PIXEL_CHECK_Y}) {{
                        try {{
                            const ctx = canvas.getContext('2d');
                            if (ctx) {{ 
                                const imageData = ctx.getImageData({PIXEL_CHECK_X}, {PIXEL_CHECK_Y}, 1, 1);
                                pixelColor = Array.from(imageData.data); 
                            }}
                        }} catch (e) {{
                            // Errors reading canvas might occur if canvas is not ready or cross-origin.
                            // Simply skip if we can't read.
                        }}
                    }}
                    return {{ speaking: speaking, pixel_color: pixelColor }};
                }}"""

                current_state = await obs_page.evaluate(js_get_full_state_function)

                speaking_status_raw = current_state["speaking"]
                pixel_color = current_state["pixel_color"]

                new_status_message = ""
                pixel_debug_message = ""

                if pixel_color is not None and are_colors_approximately_equal(pixel_color, PIXEL_LOADING_COLOR,
                                                                              PIXEL_COLOR_TOLERANCE):
                    new_status_message = "Картинка загружается (или не определена)"
                elif speaking_status_raw is True:
                    new_status_message = "Говорит"
                elif speaking_status_raw is False:
                    # Если не говорит, проверяем цвет пикселя с учетом допуска
                    if pixel_color is not None and are_colors_approximately_equal(pixel_color, CHECK_PIXEL_MUTED_COLOR,
                                                                                  PIXEL_COLOR_TOLERANCE):
                        new_status_message = "Микрофон выключен (muted)"
                    elif pixel_color is not None and are_colors_approximately_equal(pixel_color,
                                                                                    CHECK_PIXEL_DEAFENED_COLOR,
                                                                                    PIXEL_COLOR_TOLERANCE):
                        new_status_message = "Полностью заглушен (deafened)"
                    else:
                        new_status_message = "Молчит"  # Не говорит и пиксель не соответствует mute/deafen
                else:  # Если основной элемент не найден
                    new_status_message = "Элемент статуса голоса не найден."

                if pixel_color:
                    pixel_debug_message = f"[Debug Python] Полученный цвет пикселя: {pixel_color}"
                else:
                    pixel_debug_message = "[Debug Python] Цвет пикселя: Недоступен"

                # Только если статус изменился, вызываем callback
                if new_status_message != _current_voice_status:
                    _current_voice_status = new_status_message
                    status_change_callback(new_status_message, pixel_debug_message)

                await asyncio.sleep(POLLING_INTERVAL_SECONDS)  # Пауза перед следующей проверкой

            except Exception as e:
                # В случае ошибки также передаем ее в callback или выводим напрямую, если callback не может
                error_message = f"Ошибка мониторинга голоса: {e}"
                status_change_callback("Ошибка", error_message)
                await asyncio.sleep(1)  # Увеличиваем паузу при ошибке

    except Exception as e:
        print(f"Ошибка при запуске безголового браузера для мониторинга: {e}")
    finally:
        if obs_browser_context and getattr(obs_browser_context, 'browser',
                                           None) and obs_browser_context.browser.is_connected():
            print("Закрытие браузера, использованного для мониторинга.")
            await obs_browser_context.close()
