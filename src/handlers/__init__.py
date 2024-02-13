from utilities.utl_func import clean_context, extract_command


def init_conv_hl_dialog(update, context):
    clean_context(context)
    state = 'START'
    context.user_data['STATE'] = state
    context.user_data['command'] = extract_command(
        update.effective_message.text)
    context.user_data['reserve_user_data'] = {}
    context.user_data['reserve_user_data']['back'] = {}
    context.user_data['reserve_user_data']['client_data'] = {}
    context.user_data['reserve_user_data']['choose_event_info'] = {}
    context.user_data.setdefault('common_data', {})
    context.user_data.setdefault('reserve_admin_data', {'payment_id': 0})
    if not isinstance(
            context.user_data['reserve_admin_data']['payment_id'],
            int):
        context.user_data['reserve_admin_data'] = {'payment_id': 0}

    return state
