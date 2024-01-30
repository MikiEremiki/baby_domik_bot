# BabyDomikBot
Стек технологий:
- python
- pydantic
- python-telegram-bot
- googlesheet в качестве базы данных (осуществляется подготовка для переезда на postgresql + sqlalchemy)
- alembic
- docker

timeweb в качестве хостинга

___
Для запуска со сборкой контейнера миграции
`docker compose --profile migration up -d --build`
`docker compose --env-file config/.env --profile all up -d --build`

Для запуска миграции
`docker compose --profile migration up -d`

---
Для удаленной миграции (подключаюсь из Pycharm с домашней машины на Windows)
`alembic -c 'config/alembic.ini' upgrade head`

`alembic -c 'config/alembic.ini' downgrade base`

Альтернативные варианты:
- можно подключится к контейнеру бота и из под него 
сделать миграции
- запускать контейнер миграции в интерактивном режиме и выполнять команды в 
  ручную
- выполнять команды на хосте, но надо разворачивать окружение (что в общем то 
  всё равно, что первые два варианта)