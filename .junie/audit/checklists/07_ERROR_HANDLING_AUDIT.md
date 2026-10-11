# 07. Аудит обработки ошибок (Error Handling Audit)

> **Приоритет:** 🟡 Средний

---

## Чек-лист

- [ ] Backend — `@app.exception_handler` для глобальной обработки
- [ ] Backend — что возвращается при 500 ошибке?
- [ ] Frontend — `api.js`: все ли ошибки обрабатываются?
- [ ] Frontend — user-friendly сообщения при ошибках
- [ ] Graceful degradation — что если settings.json поврежден?
- [ ] Retry logic — повторная попытка при сетевой ошибке?
