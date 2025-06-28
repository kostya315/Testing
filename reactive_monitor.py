import asyncio
from playwright.async_api import async_playwright, Playwright, Page, BrowserContext, \
    TimeoutError as PlaywrightTimeoutError
from PyQt5.QtCore import QObject, pyqtSignal
import json

# Импорт зависимостей проекта
from reactive_login_flow import perform_login_flow, LOGIN_URL, LOGGED_IN_ELEMENT_SELECTOR
from image_processor import extract_and_save_discord_avatars
from reactive_model_manager import create_or_activate_model
import config_manager
import aiohttp

# --- КОНФИГУРАЦИЯ ---
POLLING_INTERVAL_SECONDS = 0.05
PIXEL_COLOR_TOLERANCE = 5


class VoiceMonitor(QObject):
    """
    Класс, который управляет Playwright, логином, настройкой и мониторингом.
    Испускает сигнал status_changed при изменении статуса голоса.
    """
    status_changed = pyqtSignal(str, str)

    def __init__(self, profile_dir, **kwargs):
        super().__init__()
        self.profile_dir = profile_dir
        self.kwargs = kwargs  # Сохраняем остальные параметры
        self._current_voice_status = "Инициализация..."

    async def run(self):
        """Основной асинхронный метод, запускающий всю логику."""
        async with async_playwright() as p:
            user_id = await self._perform_setup(p)
            if user_id:
                await self._monitor_loop(p, user_id)
            else:
                print("Не удалось получить User ID. Мониторинг не будет запущен.")

    async def _perform_setup(self, p: Playwright) -> str | None:
        """Выполняет логин и первоначальную настройку, возвращает user_id."""
        context: BrowserContext = None
        try:
            config = config_manager.load_config()
            is_setup_complete = config.get('SETUP_COMPLETE') == 'True'

            context = await p.chromium.launch_persistent_context(
                self.profile_dir,
                channel='msedge',
                headless=is_setup_complete  # Запускаем в скрытом режиме, если настройка завершена
            )
            page = context.pages[0] if context.pages else await context.new_page()

            await page.goto(LOGIN_URL, wait_until="domcontentloaded")

            # Проверка и выполнение логина
            is_logged_in = await page.is_visible(LOGGED_IN_ELEMENT_SELECTOR, timeout=5000)
            if not is_logged_in:
                if is_setup_complete:  # Если настройка была, а войти не удалось, показываем браузер
                    await context.close()
                    context = await p.chromium.launch_persistent_context(self.profile_dir, channel='msedge',
                                                                         headless=False)
                    page = await context.new_page()
                    await page.goto(LOGIN_URL)

                print("Выполняется процедура входа...")
                if not await perform_login_flow(page):
                    print("ОШИБКА: Не удалось войти.")
                    return None

            print("Пользователь успешно авторизован.")

            # Если настройка не завершена, выполняем ее
            if not is_setup_complete:
                # Извлечение User ID
                try:
                    await page.wait_for_selector('astro-island[component-export="Config"][props]', timeout=10000)
                    props_attr = await page.eval_on_selector('astro-island[component-export="Config"]',
                                                             'el => el.getAttribute("props")')
                    user_props_data = json.loads(props_attr)
                    user_id = user_props_data.get('user', [None, {}])[1].get('id', [None, None])[1]
                    if not user_id: raise ValueError("User ID не найден в props")
                except (PlaywrightTimeoutError, ValueError, json.JSONDecodeError) as e:
                    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось извлечь User ID: {e}")
                    return None

                print(f"Найден User ID: {user_id}")

                # Обработка аватаров
                async with aiohttp.ClientSession() as http_session:
                    if not await extract_and_save_discord_avatars(page, http_session, **self.kwargs):
                        print("ОШИБКА: Не удалось обработать аватары.")
                        return None

                # Создание модели
                if not await create_or_activate_model(page, config, config_manager.save_config):
                    print("ОШИБКА: Не удалось создать/активировать модель.")
                    return None

                # Сохраняем флаг успешной настройки
                config['SETUP_COMPLETE'] = 'True'
                config_manager.save_config(config)
                print("--- ПЕРВОНАЧАЛЬНАЯ НАСТРОЙКА УСПЕШНО ЗАВЕРШЕНА ---")
                await context.close()  # Закрываем браузер после настройки
                return user_id

            else:  # Если настройка уже была
                # Просто извлекаем User ID
                try:
                    await page.wait_for_selector('astro-island[component-export="Config"][props]', timeout=10000)
                    props_attr = await page.eval_on_selector('astro-island[component-export="Config"]',
                                                             'el => el.getAttribute("props")')
                    user_props_data = json.loads(props_attr)
                    user_id = user_props_data.get('user', [None, {}])[1].get('id', [None, None])[1]
                    if not user_id: raise ValueError("User ID не найден в props")
                    await context.close()  # Закрываем браузер
                    return user_id
                except Exception as e:
                    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось извлечь User ID при повторном запуске: {e}")
                    return None

        except Exception as e:
            print(f"Критическая ошибка в процессе настройки: {e}")
            if context: await context.close()
            return None

    async def _monitor_loop(self, p: Playwright, user_id: str):
        """Бесконечный цикл мониторинга статуса голоса."""
        context: BrowserContext = None
        try:
            individual_obs_url = f"{LOGIN_URL}individual/{user_id}"
            print(f"\nЗапуск мониторинга статуса голоса на: {individual_obs_url}")

            context = await p.chromium.launch_persistent_context(self.profile_dir, channel='msedge', headless=True)
            page = await context.new_page()
            await page.goto(individual_obs_url, wait_until="domcontentloaded")

            while True:
                try:
                    js_get_full_state_function = f"""
                    () => {{
                        const element = document.querySelector('div[data-discord-id="{user_id}"][data-speaking]');
                        if (!element) return {{ speaking: null, pixel_color: null }};
                        const speaking = element.getAttribute('data-speaking') === 'true';
                        const canvas = element.querySelector('canvas');
                        let pixelColor = null;
                        if (canvas && canvas.width > {self.kwargs['PIXEL_CHECK_X']} && canvas.height > {self.kwargs['PIXEL_CHECK_Y']}) {{
                            try {{
                                const ctx = canvas.getContext('2d');
                                if (ctx) {{
                                    const imageData = ctx.getImageData({self.kwargs['PIXEL_CHECK_X']}, {self.kwargs['PIXEL_CHECK_Y']}, 1, 1);
                                    pixelColor = Array.from(imageData.data);
                                }}
                            }} catch (e) {{ /* ignore */ }}
                        }}
                        return {{ speaking: speaking, pixel_color: pixelColor }};
                    }}"""

                    state = await page.evaluate(js_get_full_state_function)
                    new_status = self._determine_status_from_state(state)

                    if new_status != self._current_voice_status:
                        self._current_voice_status = new_status
                        pixel_debug = f"Цвет пикселя: {state.get('pixel_color', 'N/A')}"
                        self.status_changed.emit(new_status, pixel_debug)

                    await asyncio.sleep(POLLING_INTERVAL_SECONDS)

                except Exception as e:
                    error_message = f"Ошибка в цикле мониторинга: {e}"
                    self.status_changed.emit("Ошибка", error_message)
                    await asyncio.sleep(1)

        except Exception as e:
            print(f"Критическая ошибка при запуске мониторинга: {e}")
        finally:
            if context: await context.close()

    def _determine_status_from_state(self, state: dict) -> str:
        """Определяет строковый статус на основе данных со страницы."""
        speaking = state.get("speaking")
        pixel_color = state.get("pixel_color")

        def are_colors_approx_equal(c1, c2):
            if not c1 or not c2 or len(c1) != 4 or len(c2) != 4: return False
            return all(abs(c1[i] - c2[i]) <= PIXEL_COLOR_TOLERANCE for i in range(4))

        if speaking is True:
            return "Говорит"
        elif speaking is False:
            if are_colors_approx_equal(pixel_color, self.kwargs['ADD_PIXEL_MUTED_COLOR']):
                return "Микрофон выключен (muted)"
            elif are_colors_approx_equal(pixel_color, self.kwargs['ADD_PIXEL_DEAFENED_COLOR']):
                return "Полностью заглушен (deafened)"
            else:
                return "Молчит"
        else:
            return "Элемент статуса голоса не найден."

