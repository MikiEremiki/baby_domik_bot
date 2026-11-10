"""States and constants for /tickets_admin conversation handler."""

# ── States ──────────────────────────────────────────────────────────────────

MENU = 'MENU'               # стартовое меню: «По билету» / «По пользователю» / «По контактам»
SEARCH_USER = 'SEARCH_USER' # ожидание user_id / @username
TICKET_LIST = 'TICKET_LIST' # компактный список билетов с кнопками #ID
TICKET_CARD = 'TICKET_CARD' # карточка билета с кнопками действий
STATUS_PICK = 'STATUS_PICK' # выбор статуса кнопками
INPUT_EMAIL = 'INPUT_EMAIL' # ввод нового email
INPUT_PHONE = 'INPUT_PHONE' # ввод нового телефона
INPUT_NOTES = 'INPUT_NOTES' # ввод примечания
NOTES_MODE = 'NOTES_MODE'  # выбор режима: дополнить или перезаписать
INPUT_BASE_TICKET = 'INPUT_BASE_TICKET'  # смена типа билета
BUYER_CARD = 'BUYER_CARD'   # карточка покупателя
BUYER_TICKETS = 'BUYER_TICKETS'  # билеты покупателя
TRANSFER_PICK = 'TRANSFER_PICK'  # выбор способа переноса (по id / по параметрам)
SEARCH_TICKET_ID = 'SEARCH_TICKET_ID'  # ожидание ID билета (из меню)
SEARCH_CONTACT_PHONE = 'SEARCH_CONTACT_PHONE'  # ввод телефона для поиска
SEARCH_CONTACT_EMAIL = 'SEARCH_CONTACT_EMAIL'  # ввод email для поиска

# Pagination size for admin ticket list
PAGE_SIZE_TICKETS_ADMIN = 24
