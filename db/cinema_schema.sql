-- Кинотеатр. SQLite. Полная структура и служебные начальные записи.
-- Выполнять один раз в новой пустой базе. Пользователи и продажи не включены.
PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

-- Таблица accounts_user — Пользователи
CREATE TABLE "accounts_user" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "password" varchar(128) NOT NULL,
    "last_login" datetime NULL,
    "is_superuser" bool NOT NULL,
    "username" varchar(150) NOT NULL UNIQUE,
    "first_name" varchar(150) NOT NULL,
    "last_name" varchar(150) NOT NULL,
    "is_staff" bool NOT NULL,
    "is_active" bool NOT NULL,
    "date_joined" datetime NOT NULL,
    "email" varchar(254) NOT NULL UNIQUE,
    "phone" varchar(25) NOT NULL,
    "role" varchar(12) NOT NULL,
    "created_at" datetime NOT NULL
);

-- Таблица accounts_user_groups — Членство в группах
CREATE TABLE "accounts_user_groups" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED
);

-- Таблица accounts_user_user_permissions — Индивидуальные права
CREATE TABLE "accounts_user_user_permissions" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED
);

-- Таблица auth_group — Группы пользователей
CREATE TABLE "auth_group" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" varchar(150) NOT NULL UNIQUE
);

-- Таблица auth_group_permissions — Права групп
CREATE TABLE "auth_group_permissions" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED,
    "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED
);

-- Таблица auth_permission — Разрешения
CREATE TABLE "auth_permission" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "content_type_id" integer NOT NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED,
    "codename" varchar(100) NOT NULL,
    "name" varchar(255) NOT NULL
);

-- Таблица bookings_order — Заказы
CREATE TABLE "bookings_order" (
    "id" char(32) NOT NULL PRIMARY KEY,
    "status" varchar(12) NOT NULL,
    "created_at" datetime NOT NULL,
    "expires_at" datetime NOT NULL,
    "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "total_price" decimal NOT NULL,
    CONSTRAINT "order_nonnegative_total" CHECK ("total_price" >= '0')
);

-- Таблица bookings_payment — Платежи
CREATE TABLE "bookings_payment" (
    "id" char(32) NOT NULL PRIMARY KEY,
    "method" varchar(10) NOT NULL,
    "status" varchar(20) NOT NULL,
    "external_reference" varchar(200) NOT NULL,
    "created_at" datetime NOT NULL,
    "refunded_at" datetime NULL,
    "order_id" char(32) NOT NULL UNIQUE REFERENCES "bookings_order" ("id") DEFERRABLE INITIALLY DEFERRED,
    "recorded_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "amount" decimal NOT NULL,
    CONSTRAINT "payment_nonnegative_amount" CHECK ("amount" >= '0')
);

-- Таблица bookings_ticket — Билеты
CREATE TABLE "bookings_ticket" (
    "id" char(32) NOT NULL PRIMARY KEY,
    "qr_code_token" char(32) NOT NULL UNIQUE,
    "is_checked_in" bool NOT NULL,
    "checked_in_at" datetime NULL,
    "is_active" bool NOT NULL,
    "order_id" char(32) NOT NULL REFERENCES "bookings_order" ("id") DEFERRABLE INITIALLY DEFERRED,
    "seat_id" bigint NOT NULL REFERENCES "catalog_seat" ("id") DEFERRABLE INITIALLY DEFERRED,
    "session_id" bigint NOT NULL REFERENCES "catalog_session" ("id") DEFERRABLE INITIALLY DEFERRED,
    "price" decimal NOT NULL,
    CONSTRAINT "ticket_nonnegative_price" CHECK ("price" >= '0')
);

-- Таблица catalog_genre — Жанры
CREATE TABLE "catalog_genre" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" varchar(80) NOT NULL UNIQUE
);

-- Таблица catalog_hall — Залы
CREATE TABLE "catalog_hall" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" varchar(100) NOT NULL UNIQUE,
    "rows_count" smallint unsigned NOT NULL CHECK ("rows_count" >= 0),
    "seats_per_row" smallint unsigned NOT NULL CHECK ("seats_per_row" >= 0),
    "description" text NOT NULL,
    "cleaning_minutes" smallint unsigned NOT NULL CHECK ("cleaning_minutes" >= 0),
    "vip_multiplier" decimal NOT NULL,
    "is_active" bool NOT NULL,
    CONSTRAINT "hall_positive_grid" CHECK (("rows_count" >= 1 AND "seats_per_row" >= 1)),
    CONSTRAINT "hall_cleaning_minimum" CHECK ("cleaning_minutes" >= 15),
    CONSTRAINT "hall_vip_minimum" CHECK ("vip_multiplier" >= '1')
);

-- Таблица catalog_movie — Фильмы
CREATE TABLE "catalog_movie" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "title" varchar(200) NOT NULL,
    "description" text NOT NULL,
    "duration_minutes" smallint unsigned NOT NULL CHECK ("duration_minutes" >= 0),
    "age_limit" smallint unsigned NOT NULL CHECK ("age_limit" >= 0),
    "poster_image" varchar(100) NOT NULL,
    "is_active" bool NOT NULL,
    "genre_id" bigint NOT NULL REFERENCES "catalog_genre" ("id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "movie_positive_duration" CHECK ("duration_minutes" > 0)
);

-- Таблица catalog_seat — Места
CREATE TABLE "catalog_seat" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "row_number" smallint unsigned NOT NULL CHECK ("row_number" >= 0),
    "seat_number" smallint unsigned NOT NULL CHECK ("seat_number" >= 0),
    "seat_type" varchar(12) NOT NULL,
    "is_available" bool NOT NULL,
    "hall_id" bigint NOT NULL REFERENCES "catalog_hall" ("id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "unique_hall_seat" UNIQUE ("hall_id", "row_number", "seat_number"),
    CONSTRAINT "seat_positive_coordinates" CHECK (("row_number" >= 1 AND "seat_number" >= 1))
);

-- Таблица catalog_session — Сеансы
CREATE TABLE "catalog_session" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "start_datetime" datetime NOT NULL,
    "end_datetime" datetime NOT NULL,
    "base_price" decimal NOT NULL,
    "is_cancelled" bool NOT NULL,
    "hall_id" bigint NOT NULL REFERENCES "catalog_hall" ("id") DEFERRABLE INITIALLY DEFERRED,
    "movie_id" bigint NOT NULL REFERENCES "catalog_movie" ("id") DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "session_positive_interval" CHECK ("end_datetime" > ("start_datetime")),
    CONSTRAINT "session_positive_price" CHECK ("base_price" > '0')
);

-- Таблица django_admin_log — Журнал панели управления
CREATE TABLE "django_admin_log" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "object_id" text NULL,
    "object_repr" varchar(200) NOT NULL,
    "action_flag" smallint unsigned NOT NULL CHECK ("action_flag" >= 0),
    "change_message" text NOT NULL,
    "content_type_id" integer NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED,
    "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "action_time" datetime NOT NULL
);

-- Таблица django_content_type — Типы моделей
CREATE TABLE "django_content_type" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "app_label" varchar(100) NOT NULL,
    "model" varchar(100) NOT NULL
);

-- Таблица django_migrations — Применённые миграции
CREATE TABLE "django_migrations" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "app" varchar(255) NOT NULL,
    "name" varchar(255) NOT NULL,
    "applied" datetime NOT NULL
);

-- Таблица django_session — Сеансы входа персонала
CREATE TABLE "django_session" (
    "session_key" varchar(40) NOT NULL PRIMARY KEY,
    "session_data" text NOT NULL,
    "expire_date" datetime NOT NULL
);

-- Таблица notifications_notification — Уведомления
CREATE TABLE "notifications_notification" (
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
    "recipient" varchar(254) NOT NULL,
    "subject" varchar(200) NOT NULL,
    "body" text NOT NULL,
    "created_at" datetime NOT NULL,
    "sent_at" datetime NULL,
    "attempts" integer unsigned NOT NULL CHECK ("attempts" >= 0),
    "last_error" varchar(500) NOT NULL,
    "order_id" char(32) NULL REFERENCES "bookings_order" ("id") DEFERRABLE INITIALLY DEFERRED,
    "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED
);

-- Таблица token_blacklist_blacklistedtoken — Отозванные refresh токены
CREATE TABLE "token_blacklist_blacklistedtoken" (
    "blacklisted_at" datetime NOT NULL,
    "token_id" bigint NOT NULL UNIQUE REFERENCES "token_blacklist_outstandingtoken" ("id") DEFERRABLE INITIALLY DEFERRED,
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT
);

-- Таблица token_blacklist_outstandingtoken — Выданные refresh токены
CREATE TABLE "token_blacklist_outstandingtoken" (
    "token" text NOT NULL,
    "created_at" datetime NULL,
    "expires_at" datetime NOT NULL,
    "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED,
    "jti" varchar(255) NOT NULL UNIQUE,
    "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT
);

-- Индексы, в том числе запрет двойной продажи активного места.
CREATE INDEX "accounts_user_groups_group_id_bd11a704"
    ON "accounts_user_groups" ("group_id");
CREATE INDEX "accounts_user_groups_user_id_52b62117"
    ON "accounts_user_groups" ("user_id");
CREATE UNIQUE INDEX "accounts_user_groups_user_id_group_id_59c0b32f_uniq"
    ON "accounts_user_groups" ("user_id", "group_id");
CREATE INDEX "accounts_user_user_permissions_permission_id_113bb443"
    ON "accounts_user_user_permissions" ("permission_id");
CREATE INDEX "accounts_user_user_permissions_user_id_e4f0a161"
    ON "accounts_user_user_permissions" ("user_id");
CREATE UNIQUE INDEX "accounts_user_user_permissions_user_id_permission_id_2ab516c2_uniq"
    ON "accounts_user_user_permissions" ("user_id", "permission_id");
CREATE INDEX "auth_group_permissions_group_id_b120cbf9"
    ON "auth_group_permissions" ("group_id");
CREATE UNIQUE INDEX "auth_group_permissions_group_id_permission_id_0cd325b0_uniq"
    ON "auth_group_permissions" ("group_id", "permission_id");
CREATE INDEX "auth_group_permissions_permission_id_84c5c92e"
    ON "auth_group_permissions" ("permission_id");
CREATE INDEX "auth_permission_content_type_id_2f476e4b"
    ON "auth_permission" ("content_type_id");
CREATE UNIQUE INDEX "auth_permission_content_type_id_codename_01ab375a_uniq"
    ON "auth_permission" ("content_type_id", "codename");
CREATE INDEX "bookings_or_status_a168d7_idx"
    ON "bookings_order" ("status", "expires_at");
CREATE INDEX "bookings_order_created_by_id_fa5092cb"
    ON "bookings_order" ("created_by_id");
CREATE INDEX "bookings_order_expires_at_c1db4b45"
    ON "bookings_order" ("expires_at");
CREATE INDEX "bookings_order_status_c829e32f"
    ON "bookings_order" ("status");
CREATE INDEX "bookings_order_user_id_39236c46"
    ON "bookings_order" ("user_id");
CREATE INDEX "bookings_payment_recorded_by_id_67fabeb9"
    ON "bookings_payment" ("recorded_by_id");
CREATE INDEX "bookings_ticket_order_id_6246f93f"
    ON "bookings_ticket" ("order_id");
CREATE INDEX "bookings_ticket_seat_id_6037a201"
    ON "bookings_ticket" ("seat_id");
CREATE INDEX "bookings_ticket_session_id_02025f1c"
    ON "bookings_ticket" ("session_id");
CREATE INDEX "catalog_movie_genre_id_613aa190"
    ON "catalog_movie" ("genre_id");
CREATE INDEX "catalog_seat_hall_id_cffc2b19"
    ON "catalog_seat" ("hall_id");
CREATE INDEX "catalog_ses_hall_id_eaf6bc_idx"
    ON "catalog_session" ("hall_id", "start_datetime", "end_datetime");
CREATE INDEX "catalog_session_hall_id_987eb532"
    ON "catalog_session" ("hall_id");
CREATE INDEX "catalog_session_movie_id_c84a97e2"
    ON "catalog_session" ("movie_id");
CREATE INDEX "catalog_session_start_datetime_938820f7"
    ON "catalog_session" ("start_datetime");
CREATE INDEX "django_admin_log_content_type_id_c4bce8eb"
    ON "django_admin_log" ("content_type_id");
CREATE INDEX "django_admin_log_user_id_c564eba6"
    ON "django_admin_log" ("user_id");
CREATE UNIQUE INDEX "django_content_type_app_label_model_76bd3d3b_uniq"
    ON "django_content_type" ("app_label", "model");
CREATE INDEX "django_session_expire_date_a5c62663"
    ON "django_session" ("expire_date");
CREATE INDEX "notifications_notification_order_id_4ee8e5c3"
    ON "notifications_notification" ("order_id");
CREATE INDEX "notifications_notification_user_id_b5e8c0ff"
    ON "notifications_notification" ("user_id");
CREATE INDEX "token_blacklist_outstandingtoken_user_id_83bc629a"
    ON "token_blacklist_outstandingtoken" ("user_id");
CREATE UNIQUE INDEX "unique_active_session_seat"
    ON "bookings_ticket" ("session_id", "seat_id") WHERE "is_active";
CREATE UNIQUE INDEX "user_email_case_insensitive"
    ON "accounts_user" ((LOWER("email")));
CREATE UNIQUE INDEX "user_username_case_insensitive"
    ON "accounts_user" ((LOWER("username")));

-- Служебные записи Django: миграции, типы моделей, права и группы.

-- Начальные данные django_migrations
INSERT INTO "django_migrations" VALUES
    (1, 'contenttypes', '0001_initial', '2026-11-02 20:43:08.595857');
INSERT INTO "django_migrations" VALUES
    (2, 'contenttypes', '0002_remove_content_type_name', '2026-11-02 20:43:08.612346');
INSERT INTO "django_migrations" VALUES
    (3, 'auth', '0001_initial', '2026-11-02 20:43:08.640906');
INSERT INTO "django_migrations" VALUES
    (4, 'auth', '0002_alter_permission_name_max_length', '2026-11-02 20:43:08.657722');
INSERT INTO "django_migrations" VALUES
    (5, 'auth', '0003_alter_user_email_max_length', '2026-11-02 20:43:08.672359');
INSERT INTO "django_migrations" VALUES
    (6, 'auth', '0004_alter_user_username_opts', '2026-11-02 20:43:08.685356');
INSERT INTO "django_migrations" VALUES
    (7, 'auth', '0005_alter_user_last_login_null', '2026-11-02 20:43:08.700959');
INSERT INTO "django_migrations" VALUES
    (8, 'auth', '0006_require_contenttypes_0002', '2026-11-02 20:43:08.712117');
INSERT INTO "django_migrations" VALUES
    (9, 'auth', '0007_alter_validators_add_error_messages', '2026-11-02 20:43:08.726634');
INSERT INTO "django_migrations" VALUES
    (10, 'auth', '0008_alter_user_username_max_length', '2026-11-02 20:43:08.739957');
INSERT INTO "django_migrations" VALUES
    (11, 'auth', '0009_alter_user_last_name_max_length', '2026-11-02 20:43:08.756147');
INSERT INTO "django_migrations" VALUES
    (12, 'auth', '0010_alter_group_name_max_length', '2026-11-02 20:43:08.773609');
INSERT INTO "django_migrations" VALUES
    (13, 'auth', '0011_update_proxy_permissions', '2026-11-02 20:43:08.788351');
INSERT INTO "django_migrations" VALUES
    (14, 'auth', '0012_alter_user_first_name_max_length', '2026-11-02 20:43:08.800782');
INSERT INTO "django_migrations" VALUES
    (15, 'accounts', '0001_initial', '2026-11-02 20:43:08.829908');
INSERT INTO "django_migrations" VALUES
    (16, 'admin', '0001_initial', '2026-11-02 20:43:08.856551');
INSERT INTO "django_migrations" VALUES
    (17, 'admin', '0002_logentry_remove_auto_add', '2026-11-02 20:43:08.877238');
INSERT INTO "django_migrations" VALUES
    (18, 'admin', '0003_logentry_add_action_flag_choices', '2026-11-02 20:43:08.891025');
INSERT INTO "django_migrations" VALUES
    (19, 'catalog', '0001_initial', '2026-11-02 20:43:08.934300');
INSERT INTO "django_migrations" VALUES
    (20, 'bookings', '0001_initial', '2026-11-02 20:43:09.015917');
INSERT INTO "django_migrations" VALUES
    (21, 'bookings', '0002_alter_order_total_price_alter_payment_amount_and_more', '2026-11-02 20:43:09.060634');
INSERT INTO "django_migrations" VALUES
    (22, 'notifications', '0001_initial', '2026-11-02 20:43:09.091482');
INSERT INTO "django_migrations" VALUES
    (23, 'sessions', '0001_initial', '2026-11-02 20:43:09.118503');
INSERT INTO "django_migrations" VALUES
    (24, 'token_blacklist', '0001_initial', '2026-11-02 20:43:09.159155');
INSERT INTO "django_migrations" VALUES
    (25, 'token_blacklist', '0002_outstandingtoken_jti_hex', '2026-11-02 20:43:09.178765');
INSERT INTO "django_migrations" VALUES
    (26, 'token_blacklist', '0003_auto_20171017_2007', '2026-11-02 20:43:09.198441');
INSERT INTO "django_migrations" VALUES
    (27, 'token_blacklist', '0004_auto_20171017_2013', '2026-11-02 20:43:09.222611');
INSERT INTO "django_migrations" VALUES
    (28, 'token_blacklist', '0005_remove_outstandingtoken_jti', '2026-11-02 20:43:09.244742');
INSERT INTO "django_migrations" VALUES
    (29, 'token_blacklist', '0006_auto_20171017_2113', '2026-11-02 20:43:09.264608');
INSERT INTO "django_migrations" VALUES
    (30, 'token_blacklist', '0007_auto_20171017_2214', '2026-11-02 20:43:09.296846');
INSERT INTO "django_migrations" VALUES
    (31, 'token_blacklist', '0008_migrate_to_bigautofield', '2026-11-02 20:43:09.327884');
INSERT INTO "django_migrations" VALUES
    (32, 'token_blacklist', '0010_fix_migrate_to_bigautofield', '2026-11-02 20:43:09.355985');
INSERT INTO "django_migrations" VALUES
    (33, 'token_blacklist', '0011_linearizes_history', '2026-11-02 20:43:09.366067');
INSERT INTO "django_migrations" VALUES
    (34, 'token_blacklist', '0012_alter_outstandingtoken_user', '2026-11-02 20:43:09.388733');
INSERT INTO "django_migrations" VALUES
    (35, 'token_blacklist', '0013_alter_blacklistedtoken_options_and_more', '2026-11-02 20:43:09.407864');

-- Начальные данные django_content_type
INSERT INTO "django_content_type" VALUES
    (1, 'admin', 'logentry');
INSERT INTO "django_content_type" VALUES
    (2, 'auth', 'permission');
INSERT INTO "django_content_type" VALUES
    (3, 'auth', 'group');
INSERT INTO "django_content_type" VALUES
    (4, 'contenttypes', 'contenttype');
INSERT INTO "django_content_type" VALUES
    (5, 'sessions', 'session');
INSERT INTO "django_content_type" VALUES
    (6, 'token_blacklist', 'blacklistedtoken');
INSERT INTO "django_content_type" VALUES
    (7, 'token_blacklist', 'outstandingtoken');
INSERT INTO "django_content_type" VALUES
    (8, 'accounts', 'user');
INSERT INTO "django_content_type" VALUES
    (9, 'catalog', 'genre');
INSERT INTO "django_content_type" VALUES
    (10, 'catalog', 'hall');
INSERT INTO "django_content_type" VALUES
    (11, 'catalog', 'movie');
INSERT INTO "django_content_type" VALUES
    (12, 'catalog', 'seat');
INSERT INTO "django_content_type" VALUES
    (13, 'catalog', 'session');
INSERT INTO "django_content_type" VALUES
    (14, 'bookings', 'order');
INSERT INTO "django_content_type" VALUES
    (15, 'bookings', 'payment');
INSERT INTO "django_content_type" VALUES
    (16, 'bookings', 'ticket');
INSERT INTO "django_content_type" VALUES
    (17, 'notifications', 'notification');

-- Начальные данные auth_permission
INSERT INTO "auth_permission" VALUES
    (1, 1, 'add_logentry', 'Can add log entry');
INSERT INTO "auth_permission" VALUES
    (2, 1, 'change_logentry', 'Can change log entry');
INSERT INTO "auth_permission" VALUES
    (3, 1, 'delete_logentry', 'Can delete log entry');
INSERT INTO "auth_permission" VALUES
    (4, 1, 'view_logentry', 'Can view log entry');
INSERT INTO "auth_permission" VALUES
    (5, 2, 'add_permission', 'Can add permission');
INSERT INTO "auth_permission" VALUES
    (6, 2, 'change_permission', 'Can change permission');
INSERT INTO "auth_permission" VALUES
    (7, 2, 'delete_permission', 'Can delete permission');
INSERT INTO "auth_permission" VALUES
    (8, 2, 'view_permission', 'Can view permission');
INSERT INTO "auth_permission" VALUES
    (9, 3, 'add_group', 'Can add group');
INSERT INTO "auth_permission" VALUES
    (10, 3, 'change_group', 'Can change group');
INSERT INTO "auth_permission" VALUES
    (11, 3, 'delete_group', 'Can delete group');
INSERT INTO "auth_permission" VALUES
    (12, 3, 'view_group', 'Can view group');
INSERT INTO "auth_permission" VALUES
    (13, 4, 'add_contenttype', 'Can add content type');
INSERT INTO "auth_permission" VALUES
    (14, 4, 'change_contenttype', 'Can change content type');
INSERT INTO "auth_permission" VALUES
    (15, 4, 'delete_contenttype', 'Can delete content type');
INSERT INTO "auth_permission" VALUES
    (16, 4, 'view_contenttype', 'Can view content type');
INSERT INTO "auth_permission" VALUES
    (17, 5, 'add_session', 'Can add session');
INSERT INTO "auth_permission" VALUES
    (18, 5, 'change_session', 'Can change session');
INSERT INTO "auth_permission" VALUES
    (19, 5, 'delete_session', 'Can delete session');
INSERT INTO "auth_permission" VALUES
    (20, 5, 'view_session', 'Can view session');
INSERT INTO "auth_permission" VALUES
    (21, 6, 'add_blacklistedtoken', 'Can add Blacklisted Token');
INSERT INTO "auth_permission" VALUES
    (22, 6, 'change_blacklistedtoken', 'Can change Blacklisted Token');
INSERT INTO "auth_permission" VALUES
    (23, 6, 'delete_blacklistedtoken', 'Can delete Blacklisted Token');
INSERT INTO "auth_permission" VALUES
    (24, 6, 'view_blacklistedtoken', 'Can view Blacklisted Token');
INSERT INTO "auth_permission" VALUES
    (25, 7, 'add_outstandingtoken', 'Can add Outstanding Token');
INSERT INTO "auth_permission" VALUES
    (26, 7, 'change_outstandingtoken', 'Can change Outstanding Token');
INSERT INTO "auth_permission" VALUES
    (27, 7, 'delete_outstandingtoken', 'Can delete Outstanding Token');
INSERT INTO "auth_permission" VALUES
    (28, 7, 'view_outstandingtoken', 'Can view Outstanding Token');
INSERT INTO "auth_permission" VALUES
    (29, 8, 'add_user', 'Can add user');
INSERT INTO "auth_permission" VALUES
    (30, 8, 'change_user', 'Can change user');
INSERT INTO "auth_permission" VALUES
    (31, 8, 'delete_user', 'Can delete user');
INSERT INTO "auth_permission" VALUES
    (32, 8, 'view_user', 'Can view user');
INSERT INTO "auth_permission" VALUES
    (33, 9, 'add_genre', 'Can add genre');
INSERT INTO "auth_permission" VALUES
    (34, 9, 'change_genre', 'Can change genre');
INSERT INTO "auth_permission" VALUES
    (35, 9, 'delete_genre', 'Can delete genre');
INSERT INTO "auth_permission" VALUES
    (36, 9, 'view_genre', 'Can view genre');
INSERT INTO "auth_permission" VALUES
    (37, 10, 'add_hall', 'Can add hall');
INSERT INTO "auth_permission" VALUES
    (38, 10, 'change_hall', 'Can change hall');
INSERT INTO "auth_permission" VALUES
    (39, 10, 'delete_hall', 'Can delete hall');
INSERT INTO "auth_permission" VALUES
    (40, 10, 'view_hall', 'Can view hall');
INSERT INTO "auth_permission" VALUES
    (41, 11, 'add_movie', 'Can add movie');
INSERT INTO "auth_permission" VALUES
    (42, 11, 'change_movie', 'Can change movie');
INSERT INTO "auth_permission" VALUES
    (43, 11, 'delete_movie', 'Can delete movie');
INSERT INTO "auth_permission" VALUES
    (44, 11, 'view_movie', 'Can view movie');
INSERT INTO "auth_permission" VALUES
    (45, 12, 'add_seat', 'Can add seat');
INSERT INTO "auth_permission" VALUES
    (46, 12, 'change_seat', 'Can change seat');
INSERT INTO "auth_permission" VALUES
    (47, 12, 'delete_seat', 'Can delete seat');
INSERT INTO "auth_permission" VALUES
    (48, 12, 'view_seat', 'Can view seat');
INSERT INTO "auth_permission" VALUES
    (49, 13, 'add_session', 'Can add session');
INSERT INTO "auth_permission" VALUES
    (50, 13, 'change_session', 'Can change session');
INSERT INTO "auth_permission" VALUES
    (51, 13, 'delete_session', 'Can delete session');
INSERT INTO "auth_permission" VALUES
    (52, 13, 'view_session', 'Can view session');
INSERT INTO "auth_permission" VALUES
    (53, 14, 'add_order', 'Can add order');
INSERT INTO "auth_permission" VALUES
    (54, 14, 'change_order', 'Can change order');
INSERT INTO "auth_permission" VALUES
    (55, 14, 'delete_order', 'Can delete order');
INSERT INTO "auth_permission" VALUES
    (56, 14, 'view_order', 'Can view order');
INSERT INTO "auth_permission" VALUES
    (57, 15, 'add_payment', 'Can add payment');
INSERT INTO "auth_permission" VALUES
    (58, 15, 'change_payment', 'Can change payment');
INSERT INTO "auth_permission" VALUES
    (59, 15, 'delete_payment', 'Can delete payment');
INSERT INTO "auth_permission" VALUES
    (60, 15, 'view_payment', 'Can view payment');
INSERT INTO "auth_permission" VALUES
    (61, 16, 'add_ticket', 'Can add ticket');
INSERT INTO "auth_permission" VALUES
    (62, 16, 'change_ticket', 'Can change ticket');
INSERT INTO "auth_permission" VALUES
    (63, 16, 'delete_ticket', 'Can delete ticket');
INSERT INTO "auth_permission" VALUES
    (64, 16, 'view_ticket', 'Can view ticket');
INSERT INTO "auth_permission" VALUES
    (65, 17, 'add_notification', 'Can add notification');
INSERT INTO "auth_permission" VALUES
    (66, 17, 'change_notification', 'Can change notification');
INSERT INTO "auth_permission" VALUES
    (67, 17, 'delete_notification', 'Can delete notification');
INSERT INTO "auth_permission" VALUES
    (68, 17, 'view_notification', 'Can view notification');

-- Начальные данные auth_group
INSERT INTO "auth_group" VALUES
    (1, 'Клиенты');
INSERT INTO "auth_group" VALUES
    (2, 'Кассиры');
INSERT INTO "auth_group" VALUES
    (3, 'Администраторы');

-- Начальные данные auth_group_permissions
INSERT INTO "auth_group_permissions" VALUES
    (1, 2, 64);
INSERT INTO "auth_group_permissions" VALUES
    (2, 2, 36);
INSERT INTO "auth_group_permissions" VALUES
    (3, 2, 40);
INSERT INTO "auth_group_permissions" VALUES
    (4, 2, 44);
INSERT INTO "auth_group_permissions" VALUES
    (5, 2, 48);
INSERT INTO "auth_group_permissions" VALUES
    (6, 2, 52);
INSERT INTO "auth_group_permissions" VALUES
    (7, 2, 56);
INSERT INTO "auth_group_permissions" VALUES
    (8, 2, 60);
INSERT INTO "auth_group_permissions" VALUES
    (9, 3, 33);
INSERT INTO "auth_group_permissions" VALUES
    (10, 3, 34);
INSERT INTO "auth_group_permissions" VALUES
    (11, 3, 35);
INSERT INTO "auth_group_permissions" VALUES
    (12, 3, 36);
INSERT INTO "auth_group_permissions" VALUES
    (13, 3, 37);
INSERT INTO "auth_group_permissions" VALUES
    (14, 3, 38);
INSERT INTO "auth_group_permissions" VALUES
    (15, 3, 39);
INSERT INTO "auth_group_permissions" VALUES
    (16, 3, 40);
INSERT INTO "auth_group_permissions" VALUES
    (17, 3, 41);
INSERT INTO "auth_group_permissions" VALUES
    (18, 3, 42);
INSERT INTO "auth_group_permissions" VALUES
    (19, 3, 43);
INSERT INTO "auth_group_permissions" VALUES
    (20, 3, 44);
INSERT INTO "auth_group_permissions" VALUES
    (21, 3, 45);
INSERT INTO "auth_group_permissions" VALUES
    (22, 3, 46);
INSERT INTO "auth_group_permissions" VALUES
    (23, 3, 47);
INSERT INTO "auth_group_permissions" VALUES
    (24, 3, 48);
INSERT INTO "auth_group_permissions" VALUES
    (25, 3, 49);
INSERT INTO "auth_group_permissions" VALUES
    (26, 3, 50);
INSERT INTO "auth_group_permissions" VALUES
    (27, 3, 51);
INSERT INTO "auth_group_permissions" VALUES
    (28, 3, 52);
INSERT INTO "auth_group_permissions" VALUES
    (29, 3, 56);
INSERT INTO "auth_group_permissions" VALUES
    (30, 3, 60);
INSERT INTO "auth_group_permissions" VALUES
    (31, 3, 64);

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
