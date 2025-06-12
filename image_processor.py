import os
import sys
import tempfile
from io import BytesIO

import aiohttp
from PIL import Image


async def download_image(session: aiohttp.ClientSession, url: str) -> bytes | None:
    """Скачивает изображение по URL и возвращает его байты."""
    try:
        async with session.get(url) as response:
            response.raise_for_status()  # Вызывает исключение для статусов 4xx/5xx
            return await response.read()
    except aiohttp.ClientError as e:
        print(f"ОШИБКА: Не удалось скачать изображение с {url}: {e}")
        return None


def add_pixel_to_image(image_bytes: bytes, color: list, x: int, y: int) -> bytes | None:
    """
    Добавляет пиксель указанного цвета в (x,y) координату изображения.
    Возвращает байты модифицированного изображения в формате PNG.
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGBA")
        pixels = img.load()

        if 0 <= x < img.width and 0 <= y < img.height:
            pixels[x, y] = tuple(color)  # Устанавливаем цвет пикселя

            output_buffer = BytesIO()
            img.save(output_buffer, format="PNG")  # Сохраняем в PNG для консистентности
            return output_buffer.getvalue()
        else:
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: Координаты пикселя ({x},{y}) находятся за пределами изображения размером {img.width}x{img.height}.")
            return image_bytes  # Возвращаем исходное изображение, если пиксель вне границ
    except Exception as e:
        print(f"ОШИБКА: Не удалось обработать изображение и добавить пиксель: {e}")
        return None


def dim_image(image_bytes: bytes, dim_percentage: int) -> bytes | None:
    """
    Уменьшает яркость изображения на заданный процент.
    Возвращает байты модифицированного изображения в формате PNG.
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGBA")
        pixels = img.load()

        # Коэффициент затемнения (например, 50% = 0.5)
        dim_factor = 1.0 - (dim_percentage / 100.0)

        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = pixels[x, y]
                # Уменьшаем компоненты RGB
                r = int(r * dim_factor)
                g = int(g * dim_factor)
                b = int(b * dim_factor)
                pixels[x, y] = (r, g, b, a)

        output_buffer = BytesIO()
        img.save(output_buffer, format="PNG")
        return output_buffer.getvalue()
    except Exception as e:
        print(f"ОШИБКА: Не удалось затемнить изображение: {e}")
        return None


def overlay_image(base_image_bytes: bytes, overlay_image_bytes: bytes) -> bytes | None:
    """
    Накладывает изображение overlay_image_bytes на base_image_bytes.
    Overlay размещается в правом нижнем углу с небольшим отступом и масштабируется до 100x100px.
    Возвращает байты результирующего изображения в формате PNG.
    """
    try:
        base_img = Image.open(BytesIO(base_image_bytes)).convert("RGBA")
        overlay_img = Image.open(BytesIO(overlay_image_bytes)).convert("RGBA")

        # Масштабируем overlay до фиксированного размера 100x100px
        target_overlay_size = 100
        overlay_img = overlay_img.resize((target_overlay_size, target_overlay_size), Image.Resampling.LANCZOS)

        # Вычисляем позицию для размещения overlay (правый нижний угол с отступом)
        padding = 10  # пикселей
        x_offset = base_img.width - overlay_img.width - padding
        y_offset = base_img.height - overlay_img.height - padding

        # Создаем новое изображение для смешивания (на случай, если base_img не поддерживает прямое смешивание)
        combined_img = Image.new("RGBA", base_img.size)
        combined_img.paste(base_img, (0, 0))  # Вставляем базовое изображение

        # Накладываем overlay
        combined_img.paste(overlay_img, (x_offset, y_offset),
                           overlay_img)  # Используем overlay_img как маску для прозрачности

        output_buffer = BytesIO()
        combined_img.save(output_buffer, format="PNG")
        return output_buffer.getvalue()
    except Exception as e:
        print(f"ОШИБКА: Не удалось наложить изображение: {e}")
        return None


async def process_and_save_avatar_state(
        session: aiohttp.ClientSession,
        base_url: str,
        output_path: str,
        add_pixel: bool = False,
        pixel_color: list = None,
        pixel_x: int = None,
        pixel_y: int = None,
        add_protection_pixel: bool = False,
        protection_pixel_color: list = None,
        protection_pixel_x: int = None,
        protection_pixel_y: int = None,
        dim_percentage: int = 0,
        overlay_png_path: str = None
) -> bool:
    """
    Скачивает базовое изображение, затемняет его (если указано),
    накладывает PNG-оверлей (если указан), добавляет пиксель (если указан) и сохраняет изображение.
    """
    print(f"  Обработка: {os.path.basename(output_path)}")

    if os.path.exists(output_path):
        print(f"    Файл '{os.path.basename(output_path)}' уже существует. Пропускаю обновление.")
        return True

    img_bytes = await download_image(session, base_url)
    if img_bytes is None:
        print(f"    ОШИБКА: Не удалось скачать базовое изображение: {base_url}")
        return False

    if dim_percentage > 0:
        dimmed_bytes = dim_image(img_bytes, dim_percentage)
        if dimmed_bytes is None:
            print(f"    ОШИБКА: Не удалось затемнить изображение.")
            return False
        img_bytes = dimmed_bytes

    if add_protection_pixel:
        pixel_added_bytes = add_pixel_to_image(img_bytes, protection_pixel_color, protection_pixel_x, protection_pixel_y)
        if pixel_added_bytes is None:
            print(f"    ОШИБКА: Не удалось добавить защитный пиксель к изображению.")
            return False
        img_bytes = pixel_added_bytes

    if overlay_png_path and os.path.exists(overlay_png_path):
        try:
            with open(overlay_png_path, "rb") as f:
                overlay_bytes = f.read()

            overlaid_bytes = overlay_image(img_bytes, overlay_bytes)
            if overlaid_bytes is None:
                print(f"    ОШИБКА: Не удалось наложить PNG-оверлей на изображение.")
                return False
            img_bytes = overlaid_bytes
        except Exception as e:
            print(f"    ОШИБКА: Не удалось обработать или наложить PNG-оверлей: {e}")
            return False

    if add_pixel:
        pixel_added_bytes = add_pixel_to_image(img_bytes, pixel_color, pixel_x, pixel_y)
        if pixel_added_bytes is None:
            print(f"    ОШИБКА: Не удалось добавить пиксель к изображению.")
            return False
        img_bytes = pixel_added_bytes

    try:
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        print(f"  УСПЕХ: Файл сохранен: {os.path.basename(output_path)}")
        return True
    except Exception as e:
        print(f"  ОШИБКА: Не удалось сохранить изображение в {output_path}: {e}")
        return False


async def extract_and_save_discord_avatars(
    page,
    http_session: aiohttp.ClientSession,
    ADD_PIXEL_MUTED_COLOR: list,
    ADD_PIXEL_DEAFENED_COLOR: list,
    PIXEL_CHECK_X: int,
    PIXEL_CHECK_Y: int,
    ADD_PIXEL_PROTECTION_COLOR: list,
    DIM_PERCENTAGE: int
) -> bool:
    """
    Извлекает URL-адреса изображений Discord Avatar, скачивает их,
    добавляет пиксели (для muted/deafened) и затемняет (для inactive/muted/deafened)
    и сохраняет в локальную папку.
    """
    print("\nНачинаю извлечение и сохранение изображений Discord Avatar...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "downloaded_avatars")
    os.makedirs(output_dir, exist_ok=True)

    EXPECTED_AVATAR_FILES = [
        os.path.join(output_dir, "speaking_avatar.png"),
        os.path.join(output_dir, "inactive_avatar.png"),
        os.path.join(output_dir, "muted_avatar_with_pixel.png"),
        os.path.join(output_dir, "deafened_avatar_with_pixel.png"),
    ]

    all_avatars_exist = all(os.path.exists(f) for f in EXPECTED_AVATAR_FILES)

    if all_avatars_exist:
        print("  Все обработанные файлы аватаров уже существуют. Пропускаю извлечение и обработку.")
        return True

    svg_dir = os.path.join(script_dir, "SVG")
    mute_icon_input_path = os.path.join(svg_dir, "mutesvg.png")
    deafen_icon_input_path = os.path.join(svg_dir, "deafedsvg.png")


    try:
        discord_avatar_model_card_locator = page.locator(
            'div.flex.flex-col.rounded-lg.px-6.gap-2.py-2.justify-between.bg-neutral-200.text-neutral-800').filter(
            has_text="Discord Avatar")
        print("  Ожидаю появления карточки 'Discord Avatar'...")
        await discord_avatar_model_card_locator.wait_for(state='visible', timeout=30000)
        print("  Карточка 'Discord Avatar' найдена.")

        speaking_url = None
        inactive_url = None

        all_direct_img_locators = discord_avatar_model_card_locator.locator('img.max-h-24.max-w-full')

        print("  Ожидаю появления хотя бы одного прямого img элемента аватара (таймаут 15с)...")
        await all_direct_img_locators.first.wait_for(state='visible', timeout=15000)

        direct_imgs = await all_direct_img_locators.all()
        print(f"  Найдено {len(direct_imgs)} прямых img элементов.")

        for img_locator in direct_imgs:
            src = await img_locator.get_attribute('src')
            if src:
                has_brightness_class = 'brightness-50' in (await img_locator.get_attribute('class') or '')
                if not has_brightness_class and speaking_url is None:
                    speaking_url = src
                elif has_brightness_class and inactive_url is None:
                    inactive_url = src

        if speaking_url is None:
            print("\nОШИБКА: Не удалось найти Speaking URL. Невозможно обработать аватары.")
            return False

        speaking_url = speaking_url.split('?')[0] + '?size=1024'
        if inactive_url is None:
            inactive_url = speaking_url
        else:
            inactive_url = inactive_url.split('?')[0] + '?size=1024'

        muted_base_url = speaking_url
        deafened_base_url = speaking_url

        print("\nСкачивание, обработка и сохранение изображений...")
        print("ВНИМАНИЕ: Наложение PNG-иконок на изображения выполняется.")

        # For these calls, PIXEL_PROTECTION_X and PIXEL_PROTECTION_Y are derived from PIXEL_CHECK_X/Y in main_script.py.
        # So they must be passed or re-derived. Since they are passed, we use those passed values.
        # The ADD_PIXEL_PROTECTION_COLOR is also passed.

        if not await process_and_save_avatar_state(
                http_session,
                speaking_url, os.path.join(output_dir, "speaking_avatar.png"),
                dim_percentage=0,
                overlay_png_path=None,
                add_protection_pixel=True,
                protection_pixel_color=ADD_PIXEL_PROTECTION_COLOR,
                protection_pixel_x=PIXEL_CHECK_X,
                protection_pixel_y=PIXEL_CHECK_Y
        ): return False

        if not await process_and_save_avatar_state(
                http_session,
                inactive_url, os.path.join(output_dir, "inactive_avatar.png"),
                dim_percentage=DIM_PERCENTAGE,
                overlay_png_path=None,
                add_protection_pixel=True,
                protection_pixel_color=ADD_PIXEL_PROTECTION_COLOR,
                protection_pixel_x=PIXEL_CHECK_X,
                protection_pixel_y=PIXEL_CHECK_Y
        ): return False

        if not await process_and_save_avatar_state(
                http_session,
                muted_base_url, os.path.join(output_dir, "muted_avatar_with_pixel.png"),
                add_pixel=True, pixel_color=ADD_PIXEL_MUTED_COLOR,
                pixel_x=PIXEL_CHECK_X,
                pixel_y=PIXEL_CHECK_Y,
                dim_percentage=DIM_PERCENTAGE,
                overlay_png_path=mute_icon_input_path,
                add_protection_pixel=True,
                protection_pixel_color=ADD_PIXEL_PROTECTION_COLOR,
                protection_pixel_x=PIXEL_CHECK_X,
                protection_pixel_y=PIXEL_CHECK_Y
        ): return False

        if not await process_and_save_avatar_state(
                http_session,
                deafened_base_url, os.path.join(output_dir, "deafened_avatar_with_pixel.png"),
                add_pixel=True, pixel_color=ADD_PIXEL_DEAFENED_COLOR,
                pixel_x=PIXEL_CHECK_X,
                pixel_y=PIXEL_CHECK_Y,
                dim_percentage=DIM_PERCENTAGE,
                overlay_png_path=deafen_icon_input_path,
                add_protection_pixel=True,
                protection_pixel_color=ADD_PIXEL_PROTECTION_COLOR,
                protection_pixel_x=PIXEL_CHECK_X,
                protection_pixel_y=PIXEL_CHECK_Y
        ): return False

        print(f"\nВсе обработанные аватары сохранены в папку: {output_dir}")
        return True

    except PlaywrightTimeoutError as e:
        print(f"ОШИБКА Playwright: Таймаут во время извлечения URL-адресов аватаров: {e}")
        print(
            "  Возможно, элементы аватара не появились или селекторы устарели. Проверьте содержимое страницы в браузере.")
        return False
    except Exception as e:
        print(f"Критическая ошибка при извлечении и сохранении аватаров: {e}")
        return False
