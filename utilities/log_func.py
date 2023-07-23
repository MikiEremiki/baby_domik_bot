def join_for_log_info(id_user, text, data):
    return ": ".join([
            'Пользователь',
            str(id_user),
            f'выбрал {text}',
            data,
        ])
