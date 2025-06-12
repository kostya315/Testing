import sys
import os
import datetime
import threading
import glob  # Для работы с шаблонами файлов

# Объявляем глобальную переменную для объекта-перенаправителя, чтобы его можно было получить
_global_log_redirector = None


class LoggerRedirector:
    """
    Перенаправляет sys.stdout и sys.stderr в файл журнала.
    Сохраняет текущий вывод в 'latest.log' и создает ежедневные архивы.
    """

    def __init__(self, log_dir="logs", max_log_files=10):
        self.log_dir = log_dir
        self.max_log_files = max_log_files  # Максимальное количество архивных файлов для хранения
        # Определяем базовую директорию для логов.
        # Если приложение скомпилировано PyInstaller, sys._MEIPASS указывает на временную папку.
        # В этом случае, мы хотим, чтобы логи писались рядом с основным исполняемым файлом.
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Когда запущен как exe, sys.argv[0] - это путь к exe
            base_path = os.path.dirname(sys.argv[0])
        else:
            # Когда запущен как скрипт
            base_path = os.path.dirname(os.path.abspath(__file__))

        self.full_log_dir = os.path.join(base_path, log_dir)
        os.makedirs(self.full_log_dir, exist_ok=True)

        self.stdout = sys.stdout
        self.stderr = sys.stderr
        self.log_file = None
        self.latest_log_path = os.path.join(self.full_log_dir, "latest.log")
        self.lock = threading.Lock()  # Для потокобезопасной записи

        self._open_new_log_file()

    def _open_new_log_file(self):
        """
        Открывает новый файл журнала, управляет ротацией, оставляя только MAX_LOG_FILES последних файлов.
        """
        if self.log_file and not self.log_file.closed:
            self.log_file.close()
        # if hasattr(self, '_archive_file') and self._archive_file and not self._archive_file.closed:
        #     self._archive_file.close() # Removed as we are not using a separate archive file handle anymore

        # Шаг 1: Переименовываем текущий latest.log в файл с временной меткой (если он существует)
        if os.path.exists(self.latest_log_path):
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # Добавляем случайное число, чтобы избежать конфликтов при очень быстром запуске
            unique_timestamp_path = os.path.join(self.full_log_dir, f"{timestamp}.log")
            counter = 0
            while os.path.exists(unique_timestamp_path):
                counter += 1
                unique_timestamp_path = os.path.join(self.full_log_dir, f"{timestamp}_{counter}.log")

            try:
                os.rename(self.latest_log_path, unique_timestamp_path)
                # print(f"DEBUG: 'latest.log' переименован в '{os.path.basename(unique_timestamp_path)}'") # Отладочный вывод
            except Exception as e:
                if self.stdout:
                    self.stdout.write(
                        f"ОШИБКА: Не удалось переименовать 'latest.log' в '{os.path.basename(unique_timestamp_path)}': {e}\n")
                # В случае ошибки переименования, мы не можем гарантировать, что latest.log пуст
                # и не будет конфликтовать с новым, поэтому можем выйти или продолжить с ошибкой.
                # Для стабильности просто оставляем его как есть и попытаемся открыть новый.

        # Шаг 2: Открываем новый latest.log для записи (используем 'w' для создания нового пустого файла)
        try:
            self.log_file = open(self.latest_log_path, 'w', encoding='utf-8')
        except Exception as e:
            # Если не удалось открыть файл журнала, выводим ошибку в исходную консоль
            if self.stdout:
                self.stdout.write(f"ОШИБКА: Не удалось открыть файл журнала: {e}\n")
            self.log_file = None  # Устанавливаем None, чтобы предотвратить дальнейшие попытки записи в несуществующий файл
            self._archive_file = None  # Ensure this is explicitly None

        # Шаг 3: Удаляем старые архивные логи, чтобы сохранить только MAX_LOG_FILES
        archived_logs = []
        for f_path in glob.glob(os.path.join(self.full_log_dir, "*.log")):
            if os.path.basename(f_path) != "latest.log":  # Исключаем текущий latest.log
                archived_logs.append((os.path.getmtime(f_path), f_path))  # (время модификации, путь к файлу)

        # Сортируем по времени модификации в возрастающем порядке (самые старые первыми)
        archived_logs.sort(key=lambda x: x[0], reverse=False)

        # Удаляем лишние логи, оставляя только self.max_log_files
        # Если у нас уже есть MAX_LOG_FILES-1 архивных логов (потому что latest.log будет 10-м)
        # то мы хотим удалить самые старые, пока их не станет MAX_LOG_FILES-1
        # Или, более просто: если всего файлов (latest + archives) > MAX_LOG_FILES
        # то мы хотим, чтобы количество архивных файлов было не более MAX_LOG_FILES - 1
        num_logs_to_keep = self.max_log_files - 1  # Количество архивных логов, которые мы хотим оставить

        if len(archived_logs) > num_logs_to_keep:
            for i in range(len(archived_logs) - num_logs_to_keep):
                f_path_to_delete = archived_logs[i][1]
                try:
                    os.remove(f_path_to_delete)
                    # print(f"DEBUG: Удален старый лог-файл: {os.path.basename(f_path_to_delete)}") # Отладочный вывод
                except Exception as e:
                    if self.stdout:
                        self.stdout.write(
                            f"ОШИБКА: Не удалось удалить старый лог-файл '{os.path.basename(f_path_to_delete)}': {e}\n")

    def write(self, message):
        """Пишет сообщение в файл журнала."""
        with self.lock:
            if self.log_file and not self.log_file.closed:
                self.log_file.write(message)
                self.log_file.flush()  # Немедленно сбрасываем буфер

            # Если мы запускаемся не как exe и хотим видеть вывод в консоли во время разработки,
            # можно раскомментировать следующую строку:
            # if not getattr(sys, 'frozen', False) and self.stdout:
            #      self.stdout.write(message)
            #      self.stdout.flush()

    def flush(self):
        """Метод flush требуется для совместимости со стандартными потоками."""
        if self.log_file and not self.log_file.closed:
            self.log_file.flush()
        # Если мы выводим в оригинальный stdout (например, при разработке), также сбрасываем его
        # if not getattr(sys, 'frozen', False) and self.stdout:
        #      self.stdout.flush()

    def close(self):
        """Закрывает все открытые файлы журнала."""
        with self.lock:
            if self.log_file and not self.log_file.closed:
                self.log_file.close()
                self.log_file = None
            if hasattr(self, '_archive_file') and self._archive_file and not self._archive_file.closed:
                self._archive_file.close()
                self._archive_file = None


def setup_logging():
    """
    Настраивает перенаправление sys.stdout и sys.stderr в LoggerRedirector.
    Должен быть вызван один раз в начале приложения.
    """
    global _global_log_redirector
    if _global_log_redirector is None:
        _global_log_redirector = LoggerRedirector(max_log_files=10)  # Установлено 10 последних логов
        sys.stdout = _global_log_redirector
        sys.stderr = _global_log_redirector
        # sys.excepthook = handle_exception # Можно добавить свой обработчик исключений, если нужно
        print(
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] --- Логирование перенаправлено в '{_global_log_redirector.full_log_dir}' ---")
    else:
        print("Логирование уже настроено.")


def get_log_redirector() -> LoggerRedirector | None:
    """Возвращает текущий экземпляр LoggerRedirector."""
    return _global_log_redirector


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Кастомный обработчик неперехваченных исключений.
    Перенаправляет исключения в лог-файл.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Не вмешиваемся в KeyboardInterrupt, чтобы Ctrl+C работал
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Записываем исключение в лог-файл
    log_message = f"Неперехваченное исключение:\n"
    import traceback
    log_message += "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    if _global_log_redirector:
        _global_log_redirector.write(log_message)
    else:
        # Если логгирование еще не настроено, выводим в оригинальный stderr
        sys.__stderr__.write(log_message)

    # Можно также показать QMessageBox для пользователя, если это GUI-приложение
    # from PyQt5.QtWidgets import QApplication, QMessageBox
    # app = QApplication.instance()
    # if app:
    #     QMessageBox.critical(None, "Ошибка приложения", "Произошла критическая ошибка. Подробности в лог-файле.")
    # else:
    #     print("Критическая ошибка: Приложение не GUI, не удалось показать сообщение.")
