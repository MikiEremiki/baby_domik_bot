# 06. Аудит Frontend-архитектуры (Frontend Architecture Audit)

> **Приоритет:** 🟡 Средний
>
> **Адаптировано для baby_domik_bot:** Jinja2-шаблоны (`templates/`) и CSS (`static/css/site.css`).

---

## Чек-лист

- [ ] Jinja2-шаблоны — `templates/`: нет ли XSS через `|safe` без санитизации?
- [ ] Jinja2-шаблоны — разделение логики: нет ли сложной бизнес-логики в шаблонах?
- [ ] CSS-архитектура — `static/css/site.css`: BEM, CSS-variables, или spaghetti?
- [ ] Accessibility (a11y) — ARIA-атрибуты, keyboard navigation, contrast
- [ ] Responsive design — работает ли сайт на мобильных устройствах?
- [ ] Статические ресурсы — `static/`: корректное кэширование, нет ли битых ссылок?
