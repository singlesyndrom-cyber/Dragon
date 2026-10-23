import enum
from datetime import date, datetime

from sqlalchemy import (BigInteger, Date, LargeBinary, DateTime, Enum, Float, ForeignKey, Index, Integer, Sequence, String, text,
                        Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class GlobalRole(str, enum.Enum):
    player = "player"
    admin = "admin"


class ClubRole(str, enum.Enum):
    member = "member"
    organizer = "organizer"


class Provider(str, enum.Enum):
    email = "email"
    telegram = "telegram"
    vk = "vk"


# номер игрока: один на всю платформу, по порядку с 1001; у гостей (без аккаунта) номера нет
PLAYER_NO_SEQ = Sequence("player_no_seq", start=1001)


class User(Base):
    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}   # номер из последовательности сразу виден после flush (RETURNING)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_no: Mapped[int | None] = mapped_column(Integer, PLAYER_NO_SEQ, unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64))
    role: Mapped[GlobalRole] = mapped_column(Enum(GlobalRole), default=GlobalRole.player)
    is_banned: Mapped[bool] = mapped_column(default=False)
    tg_username: Mapped[str | None] = mapped_column(String(64))  # для связи сторон сделки
    # гость: игрок, которого организатор добавил по имени, без аккаунта; позже сливается с настоящим
    is_guest: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    guest_club_id: Mapped[int | None] = mapped_column(Integer)   # клуб, где гость был добавлен
    # статус «Создатель Клуба»: право создавать клубы. Выдаёт только админ/модератор через заявку
    is_club_creator: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # модератор: рассматривает заявки на статус «Создатель Клуба». Назначает только администратор
    is_moderator: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # отдельное согласие: передавать издателям игр мои результаты турниров вместе с ником и деклисты
    publisher_consent: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    publisher_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # растёт при смене пароля: токены входа со старой версией перестают действовать
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list["AuthAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthAccount(Base):
    """Один пользователь - несколько способов входа (email, Telegram, VK)."""
    __tablename__ = "auth_accounts"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[Provider] = mapped_column(Enum(Provider))
    external_id: Mapped[str] = mapped_column(String(255))  # email / telegram id / vk id
    password_hash: Mapped[str | None] = mapped_column(String(255))  # только для email

    user: Mapped[User] = relationship(back_populates="accounts")


class PasswordReset(Base):
    """Одноразовая ссылка на смену пароля. В базе только хеш токена: утечка таблицы не даёт войти."""
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthAttempt(Base):
    """Журнал попыток для ограничения частоты: неудачные входы, регистрации, запросы сброса.
    key - хеш email или IP, сами адреса не хранятся."""
    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_lookup", "kind", "key", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))  # для автоотчётов (блок 7)
    # часы работы для брони столов: {"0": ["12:00", "23:00"], ...} - день недели (0 = пн), нет ключа - выходной
    opening_hours: Mapped[dict | None] = mapped_column(_JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["ClubMember"]] = relationship(back_populates="club", cascade="all, delete-orphan")
    stats: Mapped["ClubStats"] = relationship(back_populates="club", uselist=False, cascade="all, delete-orphan")


class ClubVk(Base):
    """VK клуба: сообщество (токен с правом «сообщения») - беседа и личные сообщения игрокам;
    стена - токен администратора сообщества с правом «стена» (токеном сообщества VK публиковать не даёт).
    Токены хранятся зашифрованными (app/secretbox.py) и наружу не отдаются."""
    __tablename__ = "club_vk"

    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[int | None] = mapped_column(BigInteger)
    group_name: Mapped[str | None] = mapped_column(String(255))
    group_token: Mapped[str | None] = mapped_column(Text)            # зашифрован
    peer_id: Mapped[int | None] = mapped_column(BigInteger)          # устарело: одна беседа (перенесено в club_vk_chats)
    bind_code: Mapped[str | None] = mapped_column(String(16))        # код привязки беседы
    bind_game: Mapped[str | None] = mapped_column(String(16))        # для какой игры привязывается беседа
    chat_enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    dm_enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    wall_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    wall_token: Mapped[str | None] = mapped_column(Text)             # зашифрован
    wall_refresh: Mapped[str | None] = mapped_column(Text)           # зашифрован (VK ID)
    wall_device_id: Mapped[str | None] = mapped_column(String(255))
    wall_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wall_user_name: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClubVkChat(Base):
    """Беседа VK клуба для одной игры: mtg, berserk или all («все игры и новости»). Турнир уходит в беседу
    своей игры, а если её нет - в беседу all. Одна беседа может быть назначена нескольким играм."""
    __tablename__ = "club_vk_chats"
    __table_args__ = (UniqueConstraint("club_id", "game"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    game: Mapped[str] = mapped_column(String(16))
    peer_id: Mapped[int] = mapped_column(BigInteger)                 # 2000000000 + номер беседы у сообщества
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Publisher(Base):
    """Учётная запись издателя игры: видит статистику своих игр по всем клубам. Назначает администратор."""
    __tablename__ = "publishers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(128))                   # название издательства
    games: Mapped[str] = mapped_column(String(64), default="")       # "berserk,mtg"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CardPrint(Base):
    """Издание (печать) карты MTG: сет, номер, редкость, картинка, цена. Карта (Card) - одна на oracle_id,
    изданий у неё может быть десятки. Источник - выгрузка Scryfall «Default Cards»."""
    __tablename__ = "card_prints"
    __table_args__ = (Index("ix_card_prints_set", "set_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    scryfall_id: Mapped[str] = mapped_column(String(64), unique=True)
    set_code: Mapped[str] = mapped_column(String(16))
    set_name: Mapped[str | None] = mapped_column(String(255))
    collector_number: Mapped[str | None] = mapped_column(String(16))
    rarity: Mapped[str | None] = mapped_column(String(16))
    released_at: Mapped[date | None] = mapped_column(Date)
    lang: Mapped[str] = mapped_column(String(8), default="en")
    artist: Mapped[str | None] = mapped_column(String(255))
    image_url: Mapped[str | None] = mapped_column(String(512))
    image_large: Mapped[str | None] = mapped_column(String(512))
    back_image: Mapped[str | None] = mapped_column(String(512))
    prices: Mapped[dict | None] = mapped_column(_JSONB)
    finishes: Mapped[list | None] = mapped_column(_JSONB)               # nonfoil / foil / etched
    promo: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    full_art: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


class NoticeImage(Base):
    """Картинка для оповещений клуба. purpose: announce - анонсы турниров; other - итоги и новости.
    game: mtg / berserk / any. Загруженная хранится здесь (уменьшенный JPEG), арт карты - ссылкой на Scryfall."""
    __tablename__ = "notice_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="announce")
    game: Mapped[str] = mapped_column(String(16), default="any")
    source_url: Mapped[str | None] = mapped_column(String(512))       # арт карты (Scryfall art_crop)
    data: Mapped[bytes | None] = mapped_column(LargeBinary)           # загруженный файл (JPEG)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"))
    card_name: Mapped[str | None] = mapped_column(String(255))
    credit: Mapped[str | None] = mapped_column(String(255))           # «Арт: художник»
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vk_attachment: Mapped[str | None] = mapped_column(String(128))    # загружено в VK: photo<owner>_<id>_<key>
    vk_group_id: Mapped[int | None] = mapped_column(BigInteger)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClubMember(Base):
    """Игрок в клубе + его локальный рейтинг (независимый для каждого клуба)."""
    __tablename__ = "club_members"
    __table_args__ = (UniqueConstraint("club_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[ClubRole] = mapped_column(Enum(ClubRole), default=ClubRole.member)
    league_points: Mapped[int] = mapped_column(Integer, default=0)   # лига для швейцарки
    edh_bank: Mapped[float] = mapped_column(Float, default=1000.0)   # банк EDH (блок 3)
    events_played: Mapped[int] = mapped_column(Integer, default=0)
    last_bonus_week: Mapped[str | None] = mapped_column(String(10))  # '2026-W43': надбавка +150 раз в неделю
    # судья клуба: направления через запятую (mtg, edh, berserk); пусто - не судья. Назначает организатор.
    judge_games: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # сообщения бота о бронях столов: None = по роли (организатор - да, судья - нет), иначе выбор организатора/свой
    booking_notify: Mapped[bool | None] = mapped_column(nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    club: Mapped[Club] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ClubStats(Base):
    """Рейтинг клуба и агрегированная статистика прошлых турниров.
    Обновляется после завершения каждого турнира (блок 2/3)."""
    __tablename__ = "club_stats"

    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    club_rating: Mapped[float] = mapped_column(Float, default=0.0)
    tournaments_total: Mapped[int] = mapped_column(Integer, default=0)
    participants_total: Mapped[int] = mapped_column(Integer, default=0)
    avg_participants: Mapped[float] = mapped_column(Float, default=0.0)
    busiest_weekday: Mapped[int | None] = mapped_column(Integer)  # 0=пн ... 6=вс

    club: Mapped[Club] = relationship(back_populates="stats")


# ---------------- Блок 2: турниры ----------------
class TournamentFormat(str, enum.Enum):
    swiss = "swiss"
    fast_swiss = "fast_swiss"   # «Быстрый швейцарец» для «Берсерка» (по умолчанию 1 тур)
    edh = "edh"                 # реализуется в блоке 3


class TournamentStatus(str, enum.Enum):
    registration = "registration"
    running = "running"
    finished = "finished"


class MatchResult(str, enum.Enum):
    p1 = "p1"
    p2 = "p2"
    draw = "draw"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    game: Mapped[str] = mapped_column(String(32), default="mtg")  # mtg | berserk
    format: Mapped[TournamentFormat] = mapped_column(Enum(TournamentFormat))
    status: Mapped[TournamentStatus] = mapped_column(Enum(TournamentStatus), default=TournamentStatus.registration)
    rounds_total: Mapped[int | None] = mapped_column(Integer)
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # настройки как в AetherHub: описание, деклисты, кто записывает игроков, лимит, сезон лиги
    description: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    deck_policy: Mapped[str] = mapped_column(String(10), default="optional", server_default=text("'optional'"))  # none|optional|required
    self_registration: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    max_players: Mapped[int | None] = mapped_column(Integer)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id", ondelete="SET NULL"), index=True)
    judge_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # главный судья
    # анонс в чат клуба: новые турниры анонсируются не раньше чем за неделю (серии - по мере приближения).
    # server_default true: турниры, созданные до появления колонки, уже были анонсированы
    announced: Mapped[bool] = mapped_column(default=False, server_default=text("true"))
    # тестовый турнир: никаких оповещений (анонс, напоминания, итоги в чатах и ЛС)
    silent: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # бустерный драфт: {"config": {...}, "state": {"started_at", "paused_at", "offset"}} (см. app/draft.py)
    draft: Mapped[dict | None] = mapped_column(_JSONB)
    round_minutes: Mapped[int | None] = mapped_column(Integer)                 # лимит тура (драфт - 50 минут)
    round_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    series_id: Mapped[int | None] = mapped_column(Integer, index=True)   # серия еженедельных турниров: id первого

    players: Mapped[list["TournamentPlayer"]] = relationship(cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(cascade="all, delete-orphan")


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"
    __table_args__ = (UniqueConstraint("tournament_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    seed: Mapped[int] = mapped_column(Integer)  # случайный жребий для паринга 1 тура и последнего тайбрейка
    bracket: Mapped[int] = mapped_column(Integer, default=2)       # брекет колоды EDH (1-5)
    checked_in: Mapped[bool] = mapped_column(default=False)        # пришёл на ивент (отмечает организатор)
    deck_id: Mapped[int | None] = mapped_column(ForeignKey("decks.id", ondelete="SET NULL"))
    dropped: Mapped[bool] = mapped_column(default=False, server_default=text("false"))   # выбыл: без пар в следующих турах
    reminded: Mapped[bool] = mapped_column(default=False, server_default=text("false"))  # напоминание накануне отправлено
    pod: Mapped[int | None] = mapped_column(Integer)      # драфт: номер стола
    seat: Mapped[int | None] = mapped_column(Integer)     # драфт: место за столом (по часовой, с 1)

    user: Mapped[User] = relationship()


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    round_no: Mapped[int] = mapped_column(Integer)
    table_no: Mapped[int] = mapped_column(Integer)
    p1_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    p2_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = bye
    result: Mapped[MatchResult | None] = mapped_column(Enum(MatchResult))


# ---------------- Блок 3: EDH ----------------
class EdhTableStatus(str, enum.Enum):
    playing = "playing"
    finished = "finished"


class EdhTable(Base):
    __tablename__ = "edh_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    round_no: Mapped[int] = mapped_column(Integer)
    table_no: Mapped[int] = mapped_column(Integer)
    bracket: Mapped[int] = mapped_column(Integer)
    status: Mapped[EdhTableStatus] = mapped_column(Enum(EdhTableStatus), default=EdhTableStatus.playing)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))   # started_at + 70 минут
    outcome: Mapped[str | None] = mapped_column(String(16))               # win | draw | timeout
    winner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    seats: Mapped[list["EdhSeat"]] = relationship(cascade="all, delete-orphan")


class EdhSeat(Base):
    __tablename__ = "edh_seats"
    __table_args__ = (UniqueConstraint("table_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("edh_tables.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    bank_before: Mapped[float] = mapped_column(Float)
    bank_after: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)

    user: Mapped[User] = relationship()


# ---------------- Блок 4: карты и деклисты ----------------
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (UniqueConstraint("game", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game: Mapped[str] = mapped_column(String(16), index=True)            # mtg | berserk
    external_id: Mapped[str] = mapped_column(String(64))                 # oracle_id / id из JSON
    name: Mapped[str] = mapped_column(String(255))
    name_lower: Mapped[str] = mapped_column(String(255), index=True)
    name_front: Mapped[str] = mapped_column(String(255), index=True)     # лицевая сторона двусторонних карт
    set_code: Mapped[str | None] = mapped_column(String(16))
    set_name: Mapped[str | None] = mapped_column(String(128))
    type_line: Mapped[str | None] = mapped_column(String(255))
    mana_cost: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(Text)
    rarity: Mapped[str | None] = mapped_column(String(32))
    image_url: Mapped[str | None] = mapped_column(String(512))           # CDN-ссылка, без хранения файлов
    cmc: Mapped[float | None] = mapped_column(Float)
    commander_legal: Mapped[bool | None] = mapped_column()
    is_game_changer: Mapped[bool] = mapped_column(default=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)             # всё, что не вошло в основную схему
    # MTG из Scryfall: форматы, ориентировочные цены, русская печать
    legalities: Mapped[dict | None] = mapped_column(JSONB)
    prices: Mapped[dict | None] = mapped_column(JSONB)
    scryfall_uri: Mapped[str | None] = mapped_column(String(512))
    name_ru: Mapped[str | None] = mapped_column(String(255))
    name_ru_lower: Mapped[str | None] = mapped_column(String(255), index=True)
    name_ru_front: Mapped[str | None] = mapped_column(String(255), index=True)   # лицевая сторона двусторонних
    type_ru: Mapped[str | None] = mapped_column(String(255))
    text_ru: Mapped[str | None] = mapped_column(Text)


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    game: Mapped[str] = mapped_column(String(16), default="mtg")
    # игрок разрешил учитывать колоду в разделе «Мета» (блок «Популярное у игроков», без имён)
    in_meta: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # конструктор: формат MTG (deckrules.FORMATS) и кто видит колоду
    format: Mapped[str] = mapped_column(String(16), default="commander", server_default="commander")
    visibility: Mapped[str] = mapped_column(String(8), default="private", server_default="private")  # private|link|public
    share_key: Mapped[str | None] = mapped_column(String(24))      # секрет ссылки для visibility=link
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cards: Mapped[list["DeckCard"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DeckCard(Base):
    __tablename__ = "deck_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id", ondelete="SET NULL"))  # None = не найдена в базе
    name: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    is_commander: Mapped[bool] = mapped_column(default=False)
    section: Mapped[str] = mapped_column(String(16), default="main")  # main | side | commander
    # выбранное издание (картинка, сет, цена); None - издание по умолчанию из карты
    print_id: Mapped[int | None] = mapped_column(ForeignKey("card_prints.id", ondelete="SET NULL"))


# ---------------- Блок 6: новости ----------------
class ArticleStatus(str, enum.Enum):
    draft = "draft"
    published = "published"


class NewsCategory(Base):
    __tablename__ = "news_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    slug: Mapped[str] = mapped_column(String(40), unique=True)


class Article(Base):
    """club_id = NULL - глобальная статья (пишет админ), иначе новость клуба (пишет организатор)."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("news_categories.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    body_md: Mapped[str] = mapped_column(Text)          # сырой Markdown; санитайзинг - на фронтенде при рендере
    cover_url: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[ArticleStatus] = mapped_column(Enum(ArticleStatus), default=ArticleStatus.draft, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArticleTag(Base):
    __tablename__ = "article_tags"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    is_hidden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Блок 7: очередь сообщений Telegram (outbox) ----------------
from sqlalchemy import Index  # noqa: E402


class OutboxStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class OutboxMessage(Base):
    """Событие кладётся в очередь в той же транзакции, что и изменение данных;
    отправляет его отдельный процесс бота (повторы с задержкой при сбоях Telegram)."""
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_pending", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    # tg - Telegram (chat_id - чат); vk - сообщение VK (chat_id «клуб:peer_id»); vkwall - пост на стену (chat_id - клуб)
    channel: Mapped[str] = mapped_column(String(8), default="tg", server_default="tg")
    chat_id: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(512))
    parse_mode: Mapped[str] = mapped_column(String(8), default="HTML")
    buttons: Mapped[list | None] = mapped_column(JSONB)   # [[{"text", "callback_data"|"url"}]]
    status: Mapped[OutboxStatus] = mapped_column(Enum(OutboxStatus), default=OutboxStatus.pending)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(String(128), unique=True)  # защита от повторной публикации
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------- Блок 8: аукционы ----------------
class LotStatus(str, enum.Enum):
    active = "active"
    sold = "sold"
    unsold = "unsold"
    cancelled = "cancelled"


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (Index("ix_lots_status_ends", "status", "ends_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    condition: Mapped[str] = mapped_column(String(4))
    photo_file_id: Mapped[str | None] = mapped_column(String(255))   # file_id фото в Telegram
    start_price: Mapped[int] = mapped_column(Integer)
    current_price: Mapped[int | None] = mapped_column(Integer)
    leader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    bids_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[LotStatus] = mapped_column(Enum(LotStatus), default=LotStatus.active)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chat_id: Mapped[str | None] = mapped_column(String(64))           # торговый канал
    message_id: Mapped[int | None] = mapped_column(Integer)           # пост лота в канале
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(Integer)
    extended: Mapped[bool] = mapped_column(default=False)             # сработал антиснайпинг
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Deal(Base):
    """Сделка по проданному лоту. Платежи вне системы; стороны подтверждают результат,
    оценки доступны только после подтверждения обеими (status=completed)."""
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id", ondelete="CASCADE"), unique=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)
    seller_ok: Mapped[bool | None] = mapped_column()
    buyer_ok: Mapped[bool | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|completed|failed|disputed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DealRating(Base):
    __tablename__ = "deal_ratings"
    __table_args__ = (UniqueConstraint("deal_id", "from_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(8))     # роль оцениваемого: seller | buyer
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    against_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Загрузки внешних баз карт ----------------
class SyncRun(Base):
    """Журнал загрузок (Scryfall и др.): видно в админке, по нему же решается, пора ли обновлять."""
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)       # scryfall
    trigger: Mapped[str] = mapped_column(String(16))                  # auto | admin
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cards: Mapped[int] = mapped_column(Integer, default=0)
    russian: Mapped[int] = mapped_column(Integer, default=0)
    prints: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # издания (печати) карт
    error: Mapped[str | None] = mapped_column(Text)


# ---------------- Сезоны лиг ----------------
class LeagueKind(str, enum.Enum):
    edh = "edh"            # EDH: банк на сезон (старт 1000), таблица по банку
    berserk = "berserk"    # «Берсерк»: сумма очков турниров сезона (3/1/0)


class League(Base):
    """Сезон лиги клуба длиной 1-3 месяца. Турниры сезона привязываются через Tournament.league_id."""
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[LeagueKind] = mapped_column(Enum(LeagueKind))
    months: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    closed: Mapped[bool] = mapped_column(default=False, server_default=text("false"))  # закрыт досрочно вручную
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeagueMember(Base):
    """Участник сезона. Для EDH здесь банк сезона: сбрасывается до 1000 с каждым новым сезоном."""
    __tablename__ = "league_members"
    __table_args__ = (UniqueConstraint("league_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    edh_bank: Mapped[float] = mapped_column(Float, default=1000.0, server_default=text("1000"))
    last_bonus_week: Mapped[str | None] = mapped_column(String(10))
    events_played: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class ResultEdit(Base):
    """Журнал исправлений: кто и когда поменял уже введённый результат матча."""
    __tablename__ = "result_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"))
    round_no: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    before: Mapped[str] = mapped_column(String(16))
    after: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreatorRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ClubCreatorRequest(Base):
    """Заявка на статус «Создатель Клуба». У пользователя не больше одной заявки на рассмотрении:
    это держит частичный уникальный индекс, а не только проверка в коде."""
    __tablename__ = "club_creator_requests"
    __table_args__ = (Index("uq_creator_request_pending", "user_id", unique=True,
                            postgresql_where=text("status = 'pending'")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    club_name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str] = mapped_column(String(64), default="")
    about: Mapped[str] = mapped_column(Text, default="")
    reject_reason: Mapped[str] = mapped_column(String(500), default="")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Столы клуба и бронирование ----------------
class ClubTable(Base):
    """Игровой стол клуба или антикафе: его заводит организатор, участники клуба бронируют."""
    __tablename__ = "club_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    seats: Mapped[int] = mapped_column(Integer, default=4, server_default=text("4"))
    games: Mapped[str] = mapped_column(String(64), default="", server_default="")        # «MTG, EDH, Берсерк»
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TableBooking(Base):
    """Бронь стола. Пересечения по одному столу исключает API (под блокировкой строки стола)."""
    __tablename__ = "table_bookings"
    __table_args__ = (Index("ix_table_bookings_table_time", "table_id", "starts_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("club_tables.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")   # active | cancelled
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminded: Mapped[bool] = mapped_column(default=False, server_default=text("false"))   # напоминание за 2 часа
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class ServiceStatus(Base):
    """Служебные отметки: пульс бота, какая резервная копия уже отправлена, когда было последнее оповещение."""
    __tablename__ = "service_status"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class WaitlistEntry(Base):
    """Лист ожидания турнира: когда место освобождается, первого в очереди записывают автоматически."""
    __tablename__ = "tournament_waitlist"
    __table_args__ = (UniqueConstraint("tournament_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bracket: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"))
    deck_id: Mapped[int | None] = mapped_column(ForeignKey("decks.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
