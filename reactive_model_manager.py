import os
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
import asyncio

# --- КОНФИГУРАЦИЯ ---
MODEL_NAME = "Lunas support tech model"
# Папка, откуда будут загружаться ОБРАБОТАННЫЕ аватары на сайт Reactive.fugi.tech
# Эти изображения содержат специальные пиксели и оверлеи.
PROCESSED_AVATARS_FOR_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded_avatars")


async def manage_page_effects(page: Page):
    """
    Проверяет и отключает все активные чекбоксы на странице Reactive.fugi.tech.
    """
    print("\nПроверка и управление эффектами страницы (отключение всех активных чекбоксов)...")
    try:
        all_checkbox_inputs = await page.locator('input[type="checkbox"]').all()
        if all_checkbox_inputs:
            for i, checkbox_input in enumerate(all_checkbox_inputs):
                checkbox_id = await checkbox_input.get_attribute('id')
                label_text = "N/A"
                # Попытка найти связанную метку по 'for' атрибуту (label[for="id"])
                if checkbox_id:
                    try:
                        label_locator = page.locator(f'label[for="{checkbox_id}"]')
                        if await label_locator.count() > 0:
                            label_text = (await label_locator.text_content()).strip()
                    except Exception:
                        pass # Игнорируем ошибки, если метка не найдена таким способом

                is_checked = await checkbox_input.is_checked()

                if is_checked:
                    print(f"  Чекбокс '{label_text}' активен. Отключаю, кликая по метке...")
                    try:
                        # Кликаем по видимой метке, которая переключает скрытый инпут
                        # Если метка не найдена, пытаемся кликнуть по самому инпуту (менее надежно)
                        if label_text != "N/A":
                            await page.locator(f'label[for="{checkbox_id}"]').click()
                        else:
                            await checkbox_input.click() # Fallback

                        # Ждем, пока состояние скрытого input изменится на unchecked
                        await page.wait_for_function(f'document.getElementById("{checkbox_id}").checked === false', timeout=5000)
                        print(f"  Чекбокс '{label_text}' успешно отключен и подтверждено состояние 'unchecked'.")
                    except PlaywrightTimeoutError:
                        print(f"  ПРЕДУПРЕЖДЕНИЕ: Таймаут при отключении чекбокса '{label_text}' (ID: {checkbox_id}). Состояние могло не измениться в течение 5 секунд.")
                    except Exception as e:
                        print(f"  ОШИБКА при отключении чекбокса '{label_text}' (ID: {checkbox_id}): {e}")
                else:
                    print(f"  Чекбокс '{label_text}' (ID: {checkbox_id}) уже отключен. Пропускаю.")
        else:
            print("  Чекбоксы <input type=\"checkbox\"> не найдены на странице.")
    except Exception as e:
        print(f"  ОШИБКА DEBUG: Не удалось получить список всех чекбоксов: {e}")
    print("Управление эффектами завершено.\n")


async def _create_new_model(page: Page) -> bool:
    """Вспомогательная функция для создания новой модели."""
    print(f"Начинаем создание новой модели '{MODEL_NAME}'...")

    # Пути к файлам изображений, которые будут загружены на сайт Reactive.fugi.tech
    # Они берутся из PROCESSED_AVATARS_FOR_UPLOAD_FOLDER.
    temp_speaking_path = os.path.join(PROCESSED_AVATARS_FOR_UPLOAD_FOLDER, "speaking_avatar.png")
    temp_inactive_path = os.path.join(PROCESSED_AVATARS_FOR_UPLOAD_FOLDER, "inactive_avatar.png")
    temp_muted_path = os.path.join(PROCESSED_AVATARS_FOR_UPLOAD_FOLDER, "muted_avatar_with_pixel.png")
    temp_deafened_path = os.path.join(PROCESSED_AVATARS_FOR_UPLOAD_FOLDER, "deafened_avatar_with_pixel.png")

    # Проверяем наличие всех необходимых файлов в PROCESSED_AVATARS_FOR_UPLOAD_FOLDER
    if not all(os.path.exists(p) for p in
               [temp_speaking_path, temp_inactive_path, temp_muted_path, temp_deafened_path]):
        print(
            "ОШИБКА: Не все необходимые файлы изображений найдены для загрузки модели. Пожалуйста, убедитесь, что они находятся в папке 'downloaded_avatars' и были обработаны 'image_processor.py'.")
        return False

    add_button_locator = page.get_by_role("button", name="Add")

    print("\nОжидаю появления кнопки 'Add Module'...")
    try:
        await add_button_locator.wait_for(state='visible', timeout=15000)

        print("Кнопка 'Add Module' найдена и активна. Нажимаем...")
        await add_button_locator.click(timeout=15000)
        print("УСПЕХ: Нажата кнопка 'Add Module'.")

        add_model_dialog_selector = 'div[role="dialog"]:has-text("Add Model")'
        await page.wait_for_selector(add_model_dialog_selector, state='visible', timeout=10000)
        print("Диалог 'Add Model' открыт.")

    except PlaywrightTimeoutError as e:
        print(
            f"ОШИБКА Playwright: Кнопка 'Add Module' не появилась, не стала доступной или диалог 'Add Model' не открылся в течение отведенного времени: {e}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при попытке нажать 'Add Module': {e}")
        return False

    name_input_selector = 'label:has-text("Name:") input[type="text"]'
    try:
        await page.wait_for_selector(name_input_selector, state='visible', timeout=10000)
        await page.fill(name_input_selector, MODEL_NAME)
        print(f"Введено имя модели: '{MODEL_NAME}'.")
    except PlaywrightTimeoutError as e:
        print(f"ОШИБКА Playwright: Таймаут при ожидании или заполнении поля 'Name': {e}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при заполнении поля 'Name': {e}")
        return False

    upload_file_paths = [
        temp_speaking_path,
        temp_inactive_path,
        temp_muted_path,
        temp_deafened_path
    ]

    file_input_labels = [
        "Speaking Image",
        "Inactive Image",
        "Muted Image",
        "Deafened Image"
    ]

    file_inputs_in_dialog = page.locator('div.grid.grid-cols-4.gap-4 label input[type="file"]')

    for i, label_text in enumerate(file_input_labels):
        file_path = upload_file_paths[i]
        try:
            file_input_element = file_inputs_in_dialog.nth(i)
            await file_input_element.set_input_files(file_path)
            print(f"Загружен файл для '{label_text}': {os.path.basename(file_path)}")
        except PlaywrightTimeoutError as e:
            print(
                f"ОШИБКА Playwright: Таймаут при поиске или загрузке файла для '{label_text}' (индекс {i}): {e}. Проверьте селектор или доступность элемента.")
            return False
        except Exception as e:
            print(f"Критическая ошибка при загрузке файла для '{label_text}': {e}")
            return False

    save_button_selector = 'button:has-text("Save")'
    try:
        await page.wait_for_selector(save_button_selector, state='visible', timeout=10000)
        print("Нажимаем кнопку 'Save'...")
        await page.click(save_button_selector)
    except PlaywrightTimeoutError as e:
        print(f"ОШИБКА Playwright: Таймаут при ожидании или нажатии кнопки 'Save': {e}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при нажатии кнопки 'Save': {e}")
        return False

    try:
        await page.wait_for_selector(add_model_dialog_selector, state='hidden', timeout=15000)
        print("Диалог 'Add Model' закрыт.")
    except PlaywrightTimeoutError as e:
        print(
            f"ОШИБКА Playwright: Таймаут при ожидании закрытия диалога 'Add Model': {e}. Возможно, сохранение зависло или диалог не закрылся.")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при закрытии диалога 'Add Model': {e}")
        return False

    inactive_model_card_selector = f'div.flex.flex-col.rounded-lg.bg-neutral-800.border:has-text("{MODEL_NAME}")'
    try:
        await page.wait_for_selector(inactive_model_card_selector, state='visible', timeout=10000)
        print(f"Модель '{MODEL_NAME}' успешно создана (теперь неактивна).")
    except PlaywrightTimeoutError as e:
        print(
            f"ОШИБКА Playwright: Таймаут при ожидании появления только что созданной модели в неактивном состоянии: {e}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при ожидании новой модели: {e}")
        return False

    print(f"Активируем только что созданную модель '{MODEL_NAME}'...")
    try:
        await page.click(inactive_model_card_selector)
        active_model_card_selector = f'div.flex.flex-col.rounded-lg.px-6.gap-2.py-2.justify-between.bg-neutral-200.text-neutral-800:has-text("{MODEL_NAME}")'
        await page.wait_for_selector(active_model_card_selector, state='visible', timeout=10000)
        print(f"Модель '{MODEL_NAME}' активирована.")
        return True
    except PlaywrightTimeoutError as e:
        print(f"ОШИБКА Playwright: Таймаут при активации только что созданной модели: {e}")
        return False
    except Exception as e:
        print(f"ОШИБКА: Неожиданная ошибка при активации только что созданной модели: {e}")
        return False


async def create_or_activate_model(page: Page, config_data: dict, save_config_func) -> bool:
    """
    Проверяет наличие модели 'Lunas support tech model' на сайте.
    Если есть, активирует её. Если нет, создает новую.
    """

    print("Пауза 2 секунды для прогрузки модулей...")
    await asyncio.sleep(2)
    print(f"\nПроверка наличия модели '{MODEL_NAME}' на сайте...")

    # --- Управляем эффектами страницы перед проверкой модулей ---
    await manage_page_effects(page)

    all_model_cards_selector = 'div.flex.flex-col.rounded-lg.px-6.gap-2.py-2.justify-between.bg-neutral-200.text-neutral-800, div.flex.flex-col.rounded-lg.bg-neutral-800.border'

    try:
        await page.wait_for_selector(all_model_cards_selector, state='attached', timeout=10000)
    except PlaywrightTimeoutError:
        print("ПРЕДУПРЕЖДЕНИЕ: Карточки моделей не найдены на странице. Продолжаем создание новой модели.")
        if await _create_new_model(page):
            # config_data['MODEL_CREATED_COMPLETE'] = 'True' # УДАЛЕНО
            # save_config_func(config_data) # УДАЛЕНО
            return True
        return False

    model_cards = await page.locator(all_model_cards_selector).all()
    print(f"Найдено {len(model_cards)} существующих карточек моделей.")

    model_found_on_page = False
    for i, card_locator in enumerate(model_cards):
        card_text_content = await card_locator.text_content()

        if MODEL_NAME in card_text_content.strip():
            model_found_on_page = True
            print(f"Модель '{MODEL_NAME}' найдена в тексте карточки.")

            is_active_class = "bg-neutral-200" in (await card_locator.get_attribute("class") or "")
            is_inactive_class = "bg-neutral-800" in (await card_locator.get_attribute("class") or "")

            if is_active_class:
                print(f"Модель '{MODEL_NAME}' уже активна. Пропускаем создание/активацию.")
                # config_data['MODEL_CREATED_COMPLETE'] = 'True' # УДАЛЕНО
                # save_config_func(config_data) # УДАЛЕНО
                return True
            elif is_inactive_class:
                print(f"Модель '{MODEL_NAME}' найдена, но неактивна. Активируем её...")
                try:
                    await card_locator.click()
                    active_model_card_selector = f'div.flex.flex-col.rounded-lg.px-6.gap-2.py-2.justify-between.bg-neutral-200.text-neutral-800:has-text("{MODEL_NAME}")'
                    await page.wait_for_selector(active_model_card_selector, state='visible', timeout=10000)
                    print(f"Модель '{MODEL_NAME}' активирована.")
                    # config_data['MODEL_CREATED_COMPLETE'] = 'True' # УДАЛЕНО
                    # save_config_func(config_data) # УДАЛЕНО
                    return True
                except PlaywrightTimeoutError as e:
                    print(f"ОШИБКА Playwright: Таймаут при активации существующей модели: {e}")
                    return False
                except Exception as e:
                    print(f"ОШИБКА: Неожиданная ошибка при активации существующей модели: {e}")
                    return False
            else:
                print(
                    f"ВНИМАНИЕ: Модель '{MODEL_NAME}' найдена, но её состояние (активное/неактивное) не определено по классам. Продолжаем создание новой модели.")
                pass
            break

    if not model_found_on_page:
        print(f"Модель '{MODEL_NAME}' не найдена в списке. Начинаем создание новой модели...")
        if await _create_new_model(page):
            # config_data['MODEL_CREATED_COMPLETE'] = 'True' # УДАЛЕНО
            # save_config_func(config_data) # УДАЛЕНО
            return True
        return False

    return False
