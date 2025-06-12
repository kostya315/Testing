import re
import sys
from playwright.async_api import Page, Playwright, TimeoutError as PlaywrightTimeoutError

# --- КОНФИГУРАЦИЯ ---
LOGIN_URL = "https://reactive.fugi.tech/"
# Селектор элемента, который гарантированно появляется только после успешного входа
LOGGED_IN_ELEMENT_SELECTOR = 'a[href="/auth/logout"]'
COOKIE_NAME = "user"  # Имя аутентификационной куки, которую устанавливает reactive.fugi.tech


async def perform_login_flow(page: Page) -> bool:
    """
    Выполняет процесс входа на reactive.fugi.tech, начиная с нажатия кнопки.
    Возвращает True при успешной авторизации, False в противном случае.
    """
    print("Запуск пошагового процесса авторизации (видимый браузер)...")

    login_button_selector = 'a[href="/auth/discord/login"]'

    try:
        await page.wait_for_load_state('networkidle')

        await page.wait_for_selector(login_button_selector, timeout=30000, state='visible')
        print("Кнопка 'Log In With Discord' найдена. Нажимаем...")
        await page.click(login_button_selector)

        print("Ожидание перенаправления на страницу Discord OAuth2 или Reactive Images...")

        await page.wait_for_url(re.compile(r"discord.com|" + re.escape(LOGIN_URL)), timeout=60000)

        if "discord.com" in page.url:
            print(f"--- ВНИМАНИЕ: Открыта страница Discord OAuth: {page.url} ---")
            print("Пожалуйста, вручную авторизуйтесь в браузере (если потребуется).")
            print(f"После авторизации Discord перенаправит вас на {LOGIN_URL}.")

            await page.wait_for_url(LOGIN_URL, timeout=120000)
            await page.wait_for_load_state('domcontentloaded')

            await page.wait_for_selector(LOGGED_IN_ELEMENT_SELECTOR, timeout=30000,
                                         state='visible')  # Ждем кнопку выхода
            print("Авторизация Discord и вход на Reactive Images завершены (найдена кнопка выхода).")
            return True
        elif page.url == LOGIN_URL:  # Если сразу вернулись на корневой URL, проверяем, вошли ли
            try:
                await page.wait_for_load_state('domcontentloaded')

                await page.wait_for_selector(LOGGED_IN_ELEMENT_SELECTOR, timeout=10000,
                                             state='visible')  # Ждем кнопку выхода
                print("Перенаправлены на корневую страницу, пользователь авторизован (найдена кнопка выхода).")
                return True
            except PlaywrightTimeoutError:
                print("Перенаправлены на корневую страницу, но кнопка выхода не найдена. Ошибка входа.")
                return False
        else:
            print("Не удалось авторизоваться или перенаправить на ожидаемую страницу.")
            print(f"Текущий URL после попытки входа: {page.url}")
            return False

    except PlaywrightTimeoutError as e:
        print(f"ОШИБКА Playwright: Не удалось завершить процесс входа в течение отведенного времени: {e}")
        print(f"Текущий URL: {page.url}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка во время процесса входа: {e}")
        return False
