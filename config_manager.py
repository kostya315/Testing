import os
import sys

# --- КОНФИГУРАЦИЯ ---
USER_CONFIG_FILE = 'config.txt'  # Файл для пользовательских настроек
APP_CONFIG_FILE = 'app_config.txt'  # Файл для настроек приложения


# --- ЧТЕНИЕ И ЗАПИСЬ ФАЙЛА НАСТРОЕК ---
def load_config():
    """
    Загружает конфигурацию из файлов config.txt и app_config.txt.
    Создает их, если они не существуют, и добавляет отсутствующие поля.
    Возвращает объединенный словарь конфигурации.
    """
    config_data = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Загрузка и управление USER_CONFIG_FILE (config.txt) ---
    user_config_file_path = os.path.join(script_dir, USER_CONFIG_FILE)

    if not os.path.exists(user_config_file_path):
        print(f"Файл пользовательских настроек '{user_config_file_path}' не найден. Создаю новый файл.")
        try:
            with open(user_config_file_path, 'w', encoding='utf-8') as f:
                f.write("CAM_FPS=60\n")  # Стандартное значение CAM_FPS
                f.write("CAM_WIDTH=640\n")  # Добавлено: Ширина камеры
                f.write("CAM_HEIGHT=360\n")  # Добавлено: Высота камеры
                f.write("CROSS_FADE_ENABLED=True\n")
                f.write("CROSS_FADE_DURATION_MS=200\n")
                f.write("BOUNCING_ENABLED=True\n")
                f.write("RESET_ANIMATION_ON_STATUS_CHANGE=True\n")
                f.write("INSTANT_TALK_TRANSITION=True\n")
                f.write("DIM_ENABLED=True\n")
                f.write("DIM_PERCENTAGE=50\n")
            print(f"Файл '{user_config_file_path}' успешно создан.")
        except Exception as e:
            print(f"Критическая ошибка при создании файла '{user_config_file_path}': {e}")
            sys.exit(1)

    try:
        with open(user_config_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()

        # Проверка и добавление новых полей в пользовательский конфиг, если они отсутствуют
        updated = False
        if 'CAM_FPS' not in config_data:
            config_data['CAM_FPS'] = '60'
            updated = True
        if 'CAM_WIDTH' not in config_data:  # Добавлена проверка
            config_data['CAM_WIDTH'] = '640'
            updated = True
        if 'CAM_HEIGHT' not in config_data:  # Добавлена проверка
            config_data['CAM_HEIGHT'] = '360'
            updated = True
        if 'CROSS_FADE_ENABLED' not in config_data:
            config_data['CROSS_FADE_ENABLED'] = 'True'
            updated = True
        if 'CROSS_FADE_DURATION_MS' not in config_data:
            config_data['CROSS_FADE_DURATION_MS'] = '200'
            updated = True
        if 'BOUNCING_ENABLED' not in config_data:
            config_data['BOUNCING_ENABLED'] = 'True'
            updated = True
        if 'RESET_ANIMATION_ON_STATUS_CHANGE' not in config_data:
            config_data['RESET_ANIMATION_ON_STATUS_CHANGE'] = 'True'
            updated = True
        if 'INSTANT_TALK_TRANSITION' not in config_data:
            config_data['INSTANT_TALK_TRANSITION'] = 'True'
            updated = True
        if 'DIM_ENABLED' not in config_data:
            config_data['DIM_ENABLED'] = 'True'
            updated = True
        if 'DIM_PERCENTAGE' not in config_data:
            config_data['DIM_PERCENTAGE'] = '50'
            updated = True

        # Если были добавлены новые поля, сохраняем обновленный конфиг
        if updated:
            with open(user_config_file_path, 'w', encoding='utf-8') as f:
                for key, value in config_data.items():
                    # Проверяем, что ключ является пользовательской настройкой
                    if key in ['CAM_FPS', 'CAM_WIDTH', 'CAM_HEIGHT', 'CROSS_FADE_ENABLED', 'BOUNCING_ENABLED',
                               'CROSS_FADE_DURATION_MS', 'RESET_ANIMATION_ON_STATUS_CHANGE',
                               'INSTANT_TALK_TRANSITION', 'DIM_ENABLED', 'DIM_PERCENTAGE']:
                        f.write(f"{key}={value}\n")
            print(f"Файл '{user_config_file_path}' обновлен новыми настройками.")


    except Exception as e:
        print(f"ОШИБКА: Не удалось прочитать пользовательский файл настроек '{user_config_file_path}': {e}")
        # Продолжаем, но без пользовательских настроек из этого файла, чтобы не останавливать приложение

    # --- Загрузка и управление APP_CONFIG_FILE (app_config.txt) ---
    app_config_file_path = os.path.join(script_dir, APP_CONFIG_FILE)

    if not os.path.exists(app_config_file_path):
        print(f"Файл настроек приложения '{app_config_file_path}' не найден. Создаю новый файл.")
        try:
            with open(app_config_file_path, 'w', encoding='utf-8') as f:
                f.write("REACTIVE_AUTH_COOKIE=\n")
                f.write("SETUP_COMPLETE=False\n")
                f.write("MODEL_CREATED_COMPLETE=False\n")
                f.write("DRIVER_INSTALL_SUGGESTED=False\n")
            print(f"Файл '{app_config_file_path}' успешно создан.")
        except Exception as e:
            print(f"Критическая ошибка при создании файла '{app_config_file_path}': {e}")
            sys.exit(1)  # Это критическая ошибка, приложение не может работать без этого файла

    try:
        with open(app_config_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()

        # Проверка и добавление новых полей в конфиг приложения, если они отсутствуют
        updated = False
        if 'SETUP_COMPLETE' not in config_data:
            config_data['SETUP_COMPLETE'] = 'False'
            updated = True
        if 'MODEL_CREATED_COMPLETE' not in config_data:
            config_data['MODEL_CREATED_COMPLETE'] = 'False'
            updated = True
        if 'DRIVER_INSTALL_SUGGESTED' not in config_data:
            config_data['DRIVER_INSTALL_SUGGESTED'] = 'False'
            updated = True

        if updated:
            with open(app_config_file_path, 'w', encoding='utf-8') as f:
                for key, value in config_data.items():
                    # Проверяем, что ключ является настройкой приложения
                    if key in ['REACTIVE_AUTH_COOKIE', 'SETUP_COMPLETE', 'MODEL_CREATED_COMPLETE',
                               'DRIVER_INSTALL_SUGGESTED']:
                        f.write(f"{key}={value}\n")
            print(f"Файл '{app_config_file_path}' обновлен новыми настройками.")


    except Exception as e:
        print(f"Критическая ошибка при чтении файла '{app_config_file_path}': {e}")
        sys.exit(1)  # Это также критическая ошибка

    return config_data


def save_config(config_data):
    """
    Сохраняет весь словарь конфигурации обратно в соответствующие файлы:
    пользовательские настройки в config.txt, настройки приложения в app_config.txt.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_config_file_path = os.path.join(script_dir, USER_CONFIG_FILE)
    app_config_file_path = os.path.join(script_dir, APP_CONFIG_FILE)

    user_data_to_save = {}
    app_data_to_save = {}

    # Разделение данных по файлам
    for key, value in config_data.items():
        if key in ['CAM_FPS', 'CAM_WIDTH', 'CAM_HEIGHT', 'CROSS_FADE_ENABLED', 'BOUNCING_ENABLED',
                   'CROSS_FADE_DURATION_MS', 'RESET_ANIMATION_ON_STATUS_CHANGE', 'INSTANT_TALK_TRANSITION',
                   'DIM_ENABLED', 'DIM_PERCENTAGE']:  # Добавлены новые поля
            user_data_to_save[key] = value
        else:  # Все остальные настройки идут в app_config
            app_data_to_save[key] = value

    try:
        with open(user_config_file_path, 'w', encoding='utf-8') as f:
            for key, value in user_data_to_save.items():
                f.write(f"{key}={value}\n")
        print(f"Пользовательские настройки сохранены в '{user_config_file_path}'.")
    except Exception as e:
        print(f"ОШИБКА: Не удалось сохранить пользовательскую конфигурацию в '{user_config_file_path}': {e}")

    try:
        with open(app_config_file_path, 'w', encoding='utf-8') as f:
            for key, value in app_data_to_save.items():
                f.write(f"{key}={value}\n")
        print(f"Настройки приложения сохранены в '{app_config_file_path}'.")
    except Exception as e:
        print(f"ОШИБКА: Не удалось сохранить конфигурацию приложения в '{app_config_file_path}': {e}")

