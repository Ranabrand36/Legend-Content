from aiogram.fsm.state import State, StatesGroup

class AddContent(StatesGroup):
    title = State()
    description = State()
    price = State()
    payload = State()

class AddChannel(StatesGroup):
    details = State()

class AddPaymentMethod(StatesGroup):
    name = State()
    holder = State()
    account = State()
    instructions = State()

class SubmitPayment(StatesGroup):
    proof = State()

class Broadcast(StatesGroup):
    message = State()

class EditContentPrice(StatesGroup):
    value = State()

class SetBotSetting(StatesGroup):
    value = State()

class EditContentInfo(StatesGroup):
    title = State()
    description = State()
