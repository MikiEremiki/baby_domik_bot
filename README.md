# BabyDomikBot
Стек технологий:
- python
- pydantic
- python-telegram-bot
- googlesheet в качестве базы данных (осуществляется подготовка для переезда на postgresql + sqlalchemy)
- alembic
- docker
- nats (сейчас только как брокер для передачи сообщений от fastapi к боту)
- nginx
- fastapi (для обработки уведомлений от юкассы)
- postgresql (пока данные дублируются в гугле и в базе)
- sqlalchemy

timeweb в качестве хостинга

___
Для запуска со сборкой контейнера миграции

`docker compose --profile migration up -d --build`

`docker compose --env-file config/.env --profile all up -d --build`

`docker compose --env-file config/.env --profile bot up -d`

`docker compose --env-file config/.env --profile bot stop`

`docker image pull mikieremiki/baby_domik_bot`

Для создания автомиграции
`alembic -c 'config/alembic.ini' revision 
--autogenerate -m 'init'`

Для запуска миграции
`docker compose --profile migration up -d`

---
Для удаленной миграции (подключаюсь из Pycharm с домашней машины на Windows)

`alembic -c 'config/alembic.ini' upgrade head`

`alembic -c 'config/alembic.ini' downgrade base`

`.\.venv\Scripts\alembic -c 'config/alembic.ini' upgrade +1`
- запуск из PS

Альтернативные варианты:
- можно подключится к контейнеру бота и из под него 
сделать миграции
- запускать контейнер миграции в интерактивном режиме и выполнять команды в 
  ручную
- выполнять команды на хосте, но надо разворачивать окружение (что в общем то 
  всё равно, что первые два варианта)
