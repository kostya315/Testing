import asyncio
import json
import os
import re
import sys
import tempfile
from io import BytesIO
import threading  # Для запуска асинхронной логики в отдельном потоке
import atexit  # Импортируем atexit для регистрации функции завершения
import webbrowser  # Импортируем webbrowser для открытия ссылок

import aiohttp
from PIL import Image
from playwright.async_api import async_playwright, Playwright, TimeoutError as PlaywrightTimeoutError, Page, \
    BrowserContext

# Импортируем наши собственные модули
from config_manager import load_config, save_config
from image_processor import extract_and_save_discord_avatars
from reactive_login_flow import perform_login_flow, LOGIN_URL, LOGGED_IN_ELEMENT_SELECTOR, COOKIE_NAME
from reactive_model_manager import create_or_activate_model, MODEL_NAME
from reactive_monitor import monitor_voice_status, PIXEL_CHECK_X, PIXEL_CHECK_Y, POLLING_INTERVAL_SECONDS, \
    PIXEL_COLOR_TOLERANCE, CHECK_PIXEL_MUTED_COLOR, CHECK_PIXEL_DEAFENED_COLOR, PIXEL_LOADING_COLOR
# Импортируем virtual_camera и GUI элементы
import virtual_camera
from gui_elements import CameraWindow, CustomStatusHandler, create_placeholder_images_for_gui, start_gui

# Импортируем новый модуль логирования
import logging_manager

# --- CONFIGURATION ---
# Эти константы должны быть определены здесь, так как они используются в разных модулях.
ADD_PIXEL_MUTED_COLOR = [255, 0, 0, 255]  # Ярко-красный для состояния "Микрофон выключен (muted)"
ADD_PIXEL_DEAFENED_COLOR = [0, 0, 255, 255]  # Ярко-синий для состояния "Полностью заглушен (deafened)"
ADD_PIXEL_PROTECTION_COLOR = [0, 0, 0, 255]  # Черный пиксель для "защиты" от исходных цветов аватара
DIM_PERCENTAGE = 50  # Процент затемнения для неактивных/заглушенных аватаров


# --- Поток для запуска asyncio и Playwright ---
async def run_playwright_and_monitor_async(playwright_api_instance: type[Playwright], app_loop: asyncio.AbstractEventLoop, user_id: str,
                                     playwright_profile_dir: str, camera_window_instance: CameraWindow):
    """
    Запускает основную логику Playwright и мониторинга в отдельном асинхронном цикле.
    `playwright_api_instance` теперь принимает сам класс `async_playwright`.
    """
    asyncio.set_event_loop(app_loop)  # Устанавливаем цикл событий для этого потока

    browser_context: BrowserContext = None
    page: Page = None
    setup_successful_this_run = False

    # Входим в контекст Playwright внутри этого асинхронного цикла
    async with playwright_api_instance() as p_instance:
        try:
            config = load_config()  # Перезагружаем конфиг в этом потоке, чтобы получить свежие данные

            current_setup_complete = config.get('SETUP_COMPLETE')
            current_auth_cookie_present = bool(config.get('REACTIVE_AUTH_COOKIE'))
            print(f"DEBUG (Playwright thread): SETUP_COMPLETE = '{current_setup_complete}'")
            print(f"DEBUG (Playwright thread): REACTIVE_AUTH_COOKIE present = {current_auth_cookie_present}")

            launch_main_browser_headless = current_setup_complete == 'True' and current_auth_cookie_present

            print(
                f"Запускаем браузер Microsoft Edge (режим: {'скрытый' if launch_main_browser_headless else 'видимый'}) с профилем: {playwright_profile_dir}")

            browser_context = await p_instance.chromium.launch_persistent_context(
                playwright_profile_dir,
                channel='msedge',
                headless=launch_main_browser_headless
            )

            pages = browser_context.pages
            if pages:
                page = pages[0]
            else:
                page = await browser_context.new_page()

            max_goto_retries = 3
            for attempt in range(max_goto_retries):
                try:
                    await page.goto(LOGIN_URL)
                    print(f"Успешный переход на {LOGIN_URL} (попытка {attempt + 1}/{max_goto_retries}).")
                    break
                except PlaywrightTimeoutError as e:
                    print(
                        f"ОШИБКА Playwright: Таймаут при переходе на {LOGIN_URL} (попытка {attempt + 1}/{max_goto_retries}): {e}")
                    if attempt == max_goto_retries - 1:
                        raise
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Критическая ошибка при переходе на {LOGIN_URL} (попытка {attempt + 1}/{max_goto_retries}): {e}")
                    if attempt == max_goto_retries - 1:
                        raise
                    await asyncio.sleep(2)
            else:
                print(f"ОШИБКА: Не удалось перейти на {LOGIN_URL} после {max_goto_retries} попыток.")
                return

            login_successful = False

            try:
                await page.wait_for_load_state('domcontentloaded')
                is_logged_in_on_main_page = await page.is_visible(LOGGED_IN_ELEMENT_SELECTOR, timeout=5000) or \
                                            await page.is_visible(
                                                'div.flex.flex-col.rounded-lg.px-6.gap-2.py-2.justify-between.bg-neutral-200.text-neutral-800',
                                                timeout=5000)

                if is_logged_in_on_main_page:
                    print("На странице сразу обнаружены элементы, указывающие на авторизацию.")
                    login_successful = True
                else:
                    print("Элементы авторизации не обнаружены. Пользователь не авторизован.")

                    if launch_main_browser_headless:
                        print(
                            "Попытка входа в скрытом режиме не удалась. Перезапуск в видимом режиме для ручной авторизации.")
                        if browser_context and browser_context.browser and browser_context.browser.is_connected():
                            await browser_context.close()

                        browser_context = await p_instance.chromium.launch_persistent_context(
                            playwright_profile_dir,
                            channel='msedge',
                            headless=False
                        )
                        page = await browser_context.new_page()
                        await page.goto(LOGIN_URL)

                        login_successful = await perform_login_flow(page)
                    else:
                        login_successful = await perform_login_flow(page)
            except PlaywrightTimeoutError:
                print("Таймаут при проверке элементов авторизации. Запуск процесса входа...")
                if launch_main_browser_headless:
                    print(
                        "Попытка входа в скрытом режиме не удалась (таймаут). Перезапуск в видимом режиме для ручной авторизации.")
                    if browser_context and browser_context.browser and browser_context.browser.is_connected():
                        await browser_context.close()
                    browser_context = await p_instance.chromium.launch_persistent_context(
                        playwright_profile_dir,
                        channel='msedge',
                        headless=False
                    )
                    page = await browser_context.new_page() # Исправлено: page = await browser_context.new_page()
                    await page.goto(LOGIN_URL)
                    login_successful = await perform_login_flow(page)
                else:
                    login_successful = await perform_login_flow(page)
            except Exception as e:
                print(f"ОШИБКА: Неожиданная ошибка при проверке авторизации: {e}")
                if launch_main_browser_headless:
                    print(
                        "Попытка входа в скрытом режиме не удалась (ошибка). Перезапуск в видимом режиме для ручной авторизации.")
                    if browser_context and browser_context.browser and browser_context.browser.is_connected():
                        await browser_context.close()
                    browser_context = await p_instance.chromium.launch_persistent_context(
                        playwright_profile_dir,
                        channel='msedge',
                        headless=False
                    )
                    page = await browser_context.new_page()
                    await page.goto(LOGIN_URL)
                    login_successful = await perform_login_flow(page)
                else:
                    login_successful = await perform_login_flow(page)

            if login_successful:
                setup_successful_this_run = True

                all_cookies = await page.context.cookies(urls=[LOGIN_URL])
                found_cookie_value = None
                for cookie in all_cookies:
                    if cookie['name'] == COOKIE_NAME:
                        found_cookie_value = cookie['value']
                        break

                if found_cookie_value:
                    config['REACTIVE_AUTH_COOKIE'] = found_cookie_value
                    save_config(config)  # Сохраняем сразу, если кука получена
                    print(f"DEBUG (Playwright thread): REACTIVE_AUTH_COOKIE обновлен в config.txt.")
                else:
                    print(
                        f"ВНИМАНИЕ (Playwright thread): Процесс входа завершился успешно, но кука '{COOKIE_NAME}' не найдена в текущем контексте. Невозможно сохранить куку для последующих безголовых запусков.")
                    setup_successful_this_run = False
                    config['SETUP_COMPLETE'] = 'False'
                    save_config(config)

                if found_cookie_value and setup_successful_this_run:
                    try:
                        print("Пауза 2 секунды перед попыткой получить ID пользователя...")
                        await asyncio.sleep(2)
                        await page.wait_for_selector('astro-island[component-export="Config"][props]', timeout=10000)
                        props_attr = await page.eval_on_selector('astro-island[component-export="Config"]',
                                                                 'el => el.getAttribute("props")')
                        user_props_data = json.loads(props_attr)
                        user_id_from_dom = user_props_data.get('user', [None, {}])[1].get('id', [None, None])[1]

                        if user_id_from_dom:
                            print(f"\n--- ВНИМАНИЕ: Discord ID пользователя получен: {user_id_from_dom} ---")
                            user_id = user_id_from_dom

                            async with aiohttp.ClientSession() as http_session:
                                if not await extract_and_save_discord_avatars(
                                        page, http_session,
                                        ADD_PIXEL_MUTED_COLOR, ADD_PIXEL_DEAFENED_COLOR,
                                        PIXEL_CHECK_X, PIXEL_CHECK_Y, ADD_PIXEL_PROTECTION_COLOR,
                                        DIM_PERCENTAGE
                                ):
                                    print("ОШИБКА: Не удалось сохранить аватары. Настройка не завершена.")
                                    setup_successful_this_run = False

                            if setup_successful_this_run:
                                print("\nСохранение аватаров завершено.")

                            if setup_successful_this_run:
                                if not await create_or_activate_model(page, config, save_config):
                                    print("ОШИБКА: Не удалось создать/активировать модель. Настройка не завершена.")
                                    setup_successful_this_run = False

                            if setup_successful_this_run:
                                config['SETUP_COMPLETE'] = 'True'
                                save_config(config)
                                print("\n--- УСПЕХ: Аутентификация на Reactive.fugi.tech и НАСТРОЙКА завершены. ---")

                                print("Закрытие браузера, использованного для настройки...")
                                await browser_context.close()
                                browser_context = None

                                OBS_DOWNLOAD_URL = "https://obsproject.com/download"
                                if config.get('DRIVER_INSTALL_SUGGESTED') is None:
                                    config['DRIVER_INSTALL_SUGGESTED'] = 'False'
                                    save_config(config)

                                if virtual_camera.virtual_cam_obj is False and config.get(
                                        'DRIVER_INSTALL_SUGGESTED') == 'False':
                                    print(
                                        "\n----------------------------------------------------------------------------------")
                                    print("ВНИМАНИЕ: Виртуальная камера не была инициализирована.")
                                    print("Для работы программы требуется драйвер виртуальной камеры.")
                                    print("Пожалуйста, установите 'OBS Virtual Camera'.")
                                    print("Ссылка для загрузки OBS Studio (которая включает Virtual Camera):")
                                    print(f"   {OBS_DOWNLOAD_URL}")
                                    print("Открываю ссылку в браузере...")
                                    webbrowser.open(OBS_DOWNLOAD_URL)
                                    print("После установки драйвера ОБЯЗАТЕЛЬНО ПЕРЕЗАГРУЗИТЕ КОМПЬЮТЕР!")
                                    print("Затем запустите эту программу снова.")
                                    print(
                                        "----------------------------------------------------------------------------------")

                                    config['DRIVER_INSTALL_SUGGESTED'] = 'True'
                                    save_config(config)
                                    print("Флаг 'DRIVER_INSTALL_SUGGESTED' обновлен в конфигурации.")

                                elif virtual_camera.virtual_cam_obj is False and config.get(
                                        'DRIVER_INSTALL_SUGGESTED') == 'True':
                                    print(
                                        "\n----------------------------------------------------------------------------------")
                                    print("ВНИМЕНИЕ: Виртуальная камера не была инициализирована.")
                                    print(
                                        "Ранее уже была предложена установка драйвера. Убедитесь, что OBS Studio установлена (с компонентом Virtual Camera) и компьютер перезагружен.")
                                    print(
                                        "----------------------------------------------------------------------------------")
                                else:
                                    print("\n--- Запуск мониторинга статуса голоса... ---")
                                    await monitor_voice_status(p_instance, user_id, playwright_profile_dir,
                                                               virtual_camera.voice_status_callback)

                            else:
                                print("\n--- ОШИБКА: НАСТРОЙКА не была полностью завершена. ---")
                                config['SETUP_COMPLETE'] = 'False'
                                save_config(config)

                        else:
                            print("ВНИМАНИЕ: Не удалось получить ID пользователя из DOM. Мониторинг голоса недоступен.")
                            setup_successful_this_run = False
                            config['SETUP_COMPLETE'] = 'False'
                            save_config(config)

                    except PlaywrightTimeoutError as e:
                        print(
                            "ОШИБКА Playwright: Таймаут при ожидании элемента 'astro-island' для получения ID пользователя.")
                        user_id = None
                        setup_successful_this_run = False
                        config['SETUP_COMPLETE'] = 'False'
                        save_config(config)
                    except json.JSONDecodeError as e:
                        print(
                            f"ОШИБКА: Не удалось распарсить JSON из 'astro-island' props при получении ID пользователя: {e}")
                        user_id = None
                        config['SETUP_COMPLETE'] = 'False'
                        save_config(config)
                    except Exception as e:
                        print(f"ОШИБКА: Неожиданная ошибка при извлечении ID пользователя из DOM: {e}")
                        user_id = None
                        setup_successful_this_run = False
                        config['SETUP_COMPLETE'] = 'False'
                        save_config(config)
                else:
                    print("\n--- ОШИБКА: Не удалось аутентифицироваться на Reactive.fugi.tech. ---")
                    setup_successful_this_run = False
                    config['SETUP_COMPLETE'] = 'False'
                    save_config(config)

        except Exception as e:
            print(f"Критическая ошибка выполнения в Playwright потоке: {e}")
            setup_successful_this_run = False
            config['SETUP_COMPLETE'] = 'False'
            save_config(config)
        finally:
            if browser_context and getattr(browser_context, 'browser', None) and browser_context.browser.is_connected():
                print("Закрытие браузера (в блоке finally из-за ошибки).")
                await browser_context.close()
            elif browser_context is None and setup_successful_this_run:
                print("Основной браузер уже закрыт (мониторинг запущен).")
            else:
                print("Браузер не был запущен или уже закрыт.")

def start_playwright_thread(playwright_api_instance: type[Playwright], user_id: str, playwright_profile_dir: str, camera_window_instance: CameraWindow):
    """
    Запускает асинхронный цикл Playwright в отдельном потоке.
    """
    new_loop = asyncio.new_event_loop()
    new_loop.run_until_complete(run_playwright_and_monitor_async(playwright_api_instance, new_loop, user_id, playwright_profile_dir, camera_window_instance))
    new_loop.close()


# --- Главная точка входа скрипта ---
if __name__ == "__main__":
    # Настраиваем логирование в файл как можно раньше
    logging_manager.setup_logging()
    # Устанавливаем кастомный обработчик исключений, чтобы они тоже писались в лог
    sys.excepthook = logging_manager.handle_exception

    create_placeholder_images_for_gui()

    print("\nИнициализация виртуальной камеры (предварительная загрузка всех аватаров и фонов)...")
    virtual_camera.initialize_virtual_camera()
    print("Виртуальная камера инициализирована, ресурсы загружены.")

    # Определяем путь к постоянному профилю Playwright
    # Он будет находиться в подпапке 'playwright_profile' внутри директории скрипта
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    persistent_profile_dir = os.path.join(SCRIPT_DIR, "playwright_profile")
    os.makedirs(persistent_profile_dir, exist_ok=True) # Убедимся, что директория существует

    # Удаляем регистрацию для удаления временного профиля, так как теперь используем постоянный
    # atexit.register(lambda: (
    #     print(f"Удаление временного профиля Playwright: {temp_profile_dir}"),
    #     os.system(f'rmdir /s /q "{temp_profile_dir}"') if sys.platform == "win32" else os.system(f'rm -rf "{temp_profile_dir}"')
    # ))

    # Запускаем GUI в основном потоке.
    # Playwright и мониторинг будут запущены в отдельном потоке ДО запуска GUI.
    async def main_setup_and_run():
        # Передаем сам класс async_playwright в новый поток
        playwright_event_loop = asyncio.new_event_loop()
        playwright_thread = threading.Thread(target=start_playwright_thread,
                                             args=(async_playwright, None, persistent_profile_dir, None)) # Используем persistent_profile_dir
        playwright_thread.daemon = True # Поток завершится при завершении основной программы
        playwright_thread.start()

        # Запускаем GUI в основном потоке
        start_gui() # Это блокирует основной поток до закрытия GUI

    # Запускаем асинхронную функцию в основном потоке
    asyncio.run(main_setup_and_run())
