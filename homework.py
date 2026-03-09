import logging
import os
import sys
import time

from dotenv import load_dotenv
import requests
from telebot import TeleBot
from telebot.apihelper import ApiException

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=(logging.StreamHandler(sys.stdout),)
)

logger = logging.getLogger(__name__)

load_dotenv()

PRACTICUM_TOKEN = os.getenv('ya_id')
TELEGRAM_TOKEN = os.getenv('tg_token')
TELEGRAM_CHAT_ID = os.getenv('tg_chat_id')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


def check_tokens():
    """Проверяет доступность переменных окружения."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    for name, value in tokens.items():
        if not value:
            raise ValueError(
                f'Отсутствует обязательная переменная окружения: {name}'
            )


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except Exception:
        logger.exception('Сбой при отправке сообщения в Telegram')
        raise
    else:
        logger.debug('Бот отправил сообщение "%s"', message)


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
    except requests.RequestException as error:
        raise ValueError(
            f'Ошибка соединения при запросе к {ENDPOINT} '
            f'с параметрами {params}: {error}'
        ) from error
    if response.status_code != 200:
        try:
            response_text = response.text
        except Exception:
            response_text = 'Не удалось прочитать тело ответа'
        error_message = (
            f'Запрос к {ENDPOINT} с параметрами {params} завершился неудачей. '
            f'Код статуса: {response.status_code}. '
            f'Тело ответа: {response_text}'
        )
        raise requests.HTTPError(error_message)
    try:
        return response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise ValueError(
            f'Ошибка декодирования JSON в ответе от {ENDPOINT}: {error}'
        ) from error


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError(
            f'Ответ API не является словарем. '
            f'Получен тип: {type(response).__name__}'
        )
    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks"')
    if not isinstance(response['homeworks'], list):
        raise TypeError(
            f'Значение ключа "homeworks" не является списком. '
            f'Получен тип: {type(response["homeworks"]).__name__}'
        )
    return response['homeworks']


def parse_status(homework):
    """
    Извлекает статус работы из данных домашней задачи.

    Проверяет наличие ключей в словаре и формирует сообщение уведомления.
    Если статус неизвестен или ключи отсутствуют, выбрасывает исключение.
    """
    if 'homework_name' not in homework:
        raise KeyError('В ответе API отсутствует ключ "homework_name"')
    homework_name = homework['homework_name']
    homework_status = homework.get('status')
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус работы: {homework_status}')
    verdict = HOMEWORK_VERDICTS[homework_status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def process_homeworks(bot, homeworks):
    """Обрабатывает список домашних работ и отправляет уведомления."""
    for homework in homeworks:
        try:
            message = parse_status(homework)
            send_message(bot, message)
        except ValueError:
            continue


def handle_error(error, bot, last_error_message):
    """Обрабатывает возникшее исключение: логирует и отправляет уведомление."""
    current_error = str(error)
    is_telegram_error = isinstance(error, (ApiException,)) or (
        isinstance(error, Exception) and 'Telegram' in current_error
    )
    message = f'Сбой в работе программы: {error}'
    logger.error(message)
    if not is_telegram_error:
        if current_error != last_error_message:
            try:
                send_message(bot, message)
            except Exception as send_error:
                logger.debug(
                    'Не удалось отправить уведомление в Telegram: %s',
                    send_error
                )
            last_error_message = current_error
        else:
            logger.debug(
                'Повторяющаяся ошибка, сообщение в Telegram не отправлено'
            )
    else:
        logger.debug(
            'Ошибка отправки в Telegram повторная попытка уведомления отменена'
        )
    return last_error_message, True


def main():
    """Основная логика работы бота."""
    try:
        check_tokens()
    except ValueError as error:
        logger.critical(f'Программа принудительно остановлена: {error}')
        return
    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_error_message = None
    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if not homeworks:
                logger.debug('Отсутствие в ответе новых статусов')
            else:
                process_homeworks(bot, homeworks)
            timestamp = response.get('current_date', timestamp)
            last_error_message = None
        except Exception as error:
            result = handle_error(error, bot, last_error_message)
            last_error_message, should_continue = result
            if not should_continue:
                break
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
