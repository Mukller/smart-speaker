"""Состояние ожидания будильникового слова для канала устройства.

Зачем это отдельный файл. Плата с будильниковым словом на борту (ESP32 +
openWakeWord) сама слышит комнату и отсекает шум. Но протокол был устроен так,
что после hello плата обязана была **непрерывно** слать звук на сервер: сервер
не знал, что плата сейчас никого не слушает. Отсюда две беды - трафик идёт
постоянно, а распознавание запускается на шуме.

Теперь плата сообщает, умеет ли она слушать сама:

- ``local_wake: true``  - плата сама ловит слово, поток не шлёт, пока не
  поймала. Сервер держит её во сне и отбрасывает всё, что пришло мимо.
- ``local_wake: false`` - локального слова нет, сервер сам открывает окна
  прослушивания (duty cycle), чтобы микрофон не висел открытым всегда.

Сервер усыпляет плату сам, сразу после ответа: доске не нужно знать, когда
выключать микрофон, иначе каждый следующий шаг пришлось бы менять на плате.

Состояние намеренно вынесено в чистые функции без сокета и без asyncio: сокет
живёт в runva_webapi, а проверка живёт здесь и бежит на каждом коммите.
"""

SLEEPING = "sleeping"
LISTENING = "listening"
DUTY = "duty"

# Плата без локального слова: окно, когда микрофон можно держать открытым.
# 5 секунд звука хватает на фразу «джанет включи свет», а между окнами
# микрофон закрыт - иначе сервер получает поток круглые сутки.
DEFAULT_LISTEN_WINDOW = 5

# Локального слова нет, но плата всё равно умеет молчать между окнами.
MAX_LISTEN_WINDOW = 30


class WakeState(object):
    """Состояние одной платы: спит, слушает, или ждёт окна.

    Не хранит сокет и ничего не знает про сеть. Методы возвращают словарь,
    который плата должна отправить, либо None, если отвечать нечего.
    """

    def __init__(self, dev_id, local_wake, listen_window=None):
        self.dev_id = dev_id
        self.local_wake = bool(local_wake)
        self.state = SLEEPING
        # Плата без локального слова не спит вечно: у неё есть окна.
        self.duty = not self.local_wake
        if listen_window is None:
            listen_window = DEFAULT_LISTEN_WINDOW
        try:
            listen_window = int(listen_window)
        except (TypeError, ValueError):
            listen_window = DEFAULT_LISTEN_WINDOW
        self.listen_window = max(1, min(MAX_LISTEN_WINDOW, listen_window))
        # Сколько кусков звука пришло мимо, пока плата спала. Это и есть
        # видимая экономия: если число растёт, плата шлёт поток, хотя
        # будить её было нечем.
        self.dropped = 0
        self.answered = 0

    # --- что сказать плате сразу после hello -------------------------------

    def hello_reply(self):
        out = {
            "type": "hello-ok",
            "id": self.dev_id,
            "local_wake": self.local_wake,
            "state": self.state,
        }
        if self.duty:
            out["listen_window"] = self.listen_window
            out["type"] = "listen"
            self.state = LISTENING
            out["state"] = LISTENING
        return out

    # --- пришло сообщение с текстом -----------------------------------------

    def on_control(self, msg):
        """Обработать json-сообщение платы. None - неизвестный тип."""
        t = (msg or {}).get("type")
        if t == "wake":
            self.state = LISTENING
            return {"type": "listening", "id": self.dev_id}
        if t == "sleep":
            self.state = SLEEPING
            return {"type": "sleeping", "id": self.dev_id}
        if t == "window":
            # Плата сама открывает окно: локального слова нет.
            self.state = LISTENING
            return {"type": "listening", "id": self.dev_id}
        return None

    # --- пришёл ли звук -----------------------------------------------------

    def wants_audio(self):
        """Стоит ли вообще тратить ресемплирование и распознавание.

        Ключевая экономия: пока плата спит, пришедшие байты не трогаются.
        """
        return self.state == LISTENING

    def drop_audio(self, nbytes=0):
        self.dropped += 1
        return self.dropped

    # --- после ответа ------------------------------------------------------

    def after_answer(self):
        """Сервер сам усыпляет плату.

        Если этого не делать, плата продолжит слать микрофон после ответа и
        следующую команду услышит уже сама - без будильникового слова.
        """
        self.answered += 1
        if self.duty:
            # Без локального слова окна нужны постоянно, спим только между.
            return {"type": "sleeping", "seconds": self.listen_window}
        self.state = SLEEPING
        return {"type": "sleeping", "id": self.dev_id}

    def status(self):
        return {"id": self.dev_id, "state": self.state,
                "local_wake": self.local_wake, "duty": self.duty,
                "dropped": self.dropped, "answered": self.answered,
                "listen_window": self.listen_window}


def _selfcheck():
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    # Плата с будильниковым словом: после hello спит и звук не берёт.
    st = WakeState(1, local_wake=True)
    r = st.hello_reply()
    want(r["type"] == "hello-ok", "hello должен отвечать hello-ok")
    want(r["local_wake"] is True, "плата должна знать, что слово локальное")
    want(r["state"] == SLEEPING, "после hello плата спит, а не слушает")
    want("listen_window" not in r, "локальной плате окно не нужно")
    want(st.wants_audio() is False, "спящая плата не должна жечь звук")

    # Пока спит - байты отбрасываются, а не распознаются.
    st.drop_audio(320)
    st.drop_audio(320)
    want(st.dropped == 2, "спящая плата должна считать отброшенное")
    want(st.status()["dropped"] == 2, "отброшенное должно быть видно в статусе")

    # Слово поймали - плата просыпается.
    r = st.on_control({"type": "wake"})
    want(r and r["type"] == "listening", "после wake плата слушает")
    want(st.wants_audio() is True, "проснувшаяся плата принимает звук")

    # Поток пришёл, ответили - сервер сам усыпляет.
    r = st.after_answer()
    want(r and r["type"] == "sleeping", "сервер обязан усыпить плату")
    want(st.wants_audio() is False,
         "после ответа плата обязана перестать слать микрофон, "
         "иначе следующую команду услышит без будильникового слова")

    # Плата без локального слова получает окна, а не вечный поток.
    st2 = WakeState(2, local_wake=False)
    r = st2.hello_reply()
    want(r["type"] == "listen", "без локального слова нужны окна")
    want(r["listen_window"] == DEFAULT_LISTEN_WINDOW,
         "окно должно быть разумным, а не нулевым")
    want(st2.wants_audio() is True, "в окне плата слушает")
    r = st2.after_answer()
    want(r and r["seconds"] == DEFAULT_LISTEN_WINDOW,
         "после ответа без локального слова окно должно возобновиться")

    # Окно не должно превращаться в вечное включение.
    st3 = WakeState(3, local_wake=False, listen_window=9999)
    want(st3.listen_window == MAX_LISTEN_WINDOW,
         "окно обязано быть ограничено, иначе микрофон включён всегда")
    st4 = WakeState(4, local_wake=False, listen_window="мусор")
    want(st4.listen_window == DEFAULT_LISTEN_WINDOW,
         "битое окно должно падать на значение по умолчанию")

    # Неизвестный тип не должен ронять соединение.
    want(WakeState(5, True).on_control({"type": "что-то"}) is None,
         "неизвестный тип должен возвращать None, а не исключение")
    want(WakeState(6, True).on_control(None) is None,
         "пустое сообщение не должно ронять соединение")

    # Плата может уснуть сама, если всё же решила.
    st5 = WakeState(7, local_wake=True)
    st5.on_control({"type": "wake"})
    r = st5.on_control({"type": "sleep"})
    want(r and r["type"] == "sleeping", "плата может уснуть сама")
    want(st5.wants_audio() is False, "после сна звук не принимается")

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_wake: плата спит, будится по слову и засыпает сама")
    print("ИТОГ: провалено %d" % len(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(_selfcheck())
