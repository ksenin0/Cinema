/* Cashier presentation only. The API owns prices, reservations and payment transitions. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const root = $("main");
  const token = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const zone = root.dataset.timeZone;
  const state = { sessions: [], session: null, seats: [], selected: new Set(), busy: false,
    mapReady: false, mapLoading: false, generation: 0, clockOffset: 0, orders: [] };
  const currency = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 });
  const money = cents => currency.format(cents / 100);
  const cents = value => Math.round(Number(value) * 100);
  const dt = (value, opts) => new Intl.DateTimeFormat("ru-RU", { timeZone: zone, ...opts }).format(new Date(value));
  const time = value => dt(value, { hour: "2-digit", minute: "2-digit" });
  const date = value => dt(value, { day: "numeric", month: "long" });
  const dateKey = value => new Intl.DateTimeFormat("sv-SE", { timeZone: zone }).format(new Date(value));
  const now = () => Date.now() + state.clockOffset;
  const sellable = () => state.session && new Date(state.session.start_datetime).getTime() > now();
  const node = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  function notice(text = "", type = "") {
    $("message").textContent = text;
    $("message").className = `notice ${type}`;
    $("message").hidden = !text;
  }
  function details(error) {
    const flatten = value => typeof value === "string" ? [value] : value && typeof value === "object" ? Object.values(value).flatMap(flatten) : [];
    return [...new Set(flatten(error.errors || error.message))].join(" ") || "Не удалось выполнить запрос.";
  }
  async function api(url, data) {
    let response;
    try {
      response = await fetch(url, { method: data === undefined ? "GET" : "POST",
        credentials: "same-origin", mode: "same-origin", cache: "no-store",
        headers: { Accept: "application/json", ...(data === undefined ? {} : { "Content-Type": "application/json", "X-CSRFToken": token }) },
        body: data === undefined ? undefined : JSON.stringify(data) });
    } catch (_) {
      throw Object.assign(new Error("Нет связи с сервером. Проверьте подключение и обновите данные."), { uncertain: data !== undefined });
    }
    if (response.redirected || response.status === 401) {
      throw Object.assign(new Error("Сеанс входа завершён. Войдите в кассу заново."), { auth: true });
    }
    let result;
    try { result = await response.json(); }
    catch (_) { throw Object.assign(new Error("Сервер вернул неожиданный ответ. Обновите данные."), { uncertain: data !== undefined }); }
    if (!response.ok) throw Object.assign(new Error(details(result)), { status: response.status, uncertain: data !== undefined && response.status >= 500 });
    return result;
  }
  function showError(error) {
    notice(error.message, "error");
    if (error.auth) {
      const link = node("a", "button secondary", "Войти снова");
      link.href = root.dataset.loginUrl;
      $("message").append(document.createTextNode(" "), link);
    }
  }
  function selectedSeats() { return state.seats.filter(s => state.selected.has(s.id)); }
  function renderCart() {
    const seats = selectedSeats();
    const list = $("cart-items");
    list.replaceChildren();
    if (!seats.length) list.append(node("li", "empty", "Нажмите на свободное кресло"));
    for (const seat of seats) {
      const item = node("li", "cart-item");
      const label = node("span", "", `Ряд ${seat.row_number} · Место ${seat.seat_number}`);
      label.append(node("small", "", seat.seat_type === "vip" ? "VIP" : seat.seat_type === "disabled" ? "МГН" : "Стандарт"));
      const remove = node("button", "remove-seat", "×");
      remove.type = "button"; remove.disabled = state.busy;
      remove.setAttribute("aria-label", `Убрать ряд ${seat.row_number}, место ${seat.seat_number}`);
      remove.addEventListener("click", () => toggleSeat(seat.id));
      item.append(label, node("span", "", money(cents(seat.price))), remove); list.append(item);
    }
    $("cart-session").textContent = state.session ? `${state.session.movie_title} · ${date(state.session.start_datetime)}, ${time(state.session.start_datetime)} · ${state.session.hall_name}` : "Выберите места на схеме";
    $("total-price").textContent = money(seats.reduce((sum, s) => sum + cents(s.price), 0));
    $("ticket-count").textContent = `Билетов: ${seats.length}`;
    const disabled = !seats.length || state.busy || !state.mapReady || !sellable();
    $("pay-cash").disabled = disabled; $("pay-card").disabled = disabled;
    $("clear-selection").disabled = !seats.length || state.busy;
    $("refresh-map").disabled = !state.session || state.busy || state.mapLoading;
    $("session-date").disabled = state.busy || !state.sessions.length;
    $("session-search").disabled = state.busy;
    $("refresh-schedule").disabled = state.busy;
    document.querySelectorAll(".session-card").forEach(button => { button.disabled = state.busy; });
  }
  function toggleSeat(id) {
    if (state.busy || !state.mapReady || !sellable()) return;
    const seat = state.seats.find(s => s.id === id);
    if (!seat || seat.status !== "free") return;
    if (state.selected.has(id)) state.selected.delete(id);
    else if (state.selected.size < 20) state.selected.add(id);
    else { notice("В одной продаже может быть не больше 20 билетов.", "error"); return; }
    // Keep focus on the clicked seat; polling also updates buttons in place.
    updateSeatButtons(); renderCart();
  }
  function updateSeatButtons() {
    const seats = new Map(state.seats.map(s => [s.id, s]));
    document.querySelectorAll("button[data-seat-id]").forEach(button => {
      const seat = seats.get(Number(button.dataset.seatId));
      const chosen = state.selected.has(seat.id);
      const category = seat.seat_type === "vip" ? "vip" : seat.seat_type === "disabled" ? "accessible" : "";
      button.className = `seat ${category} ${chosen ? "chosen" : seat.status}`;
      button.disabled = state.busy || seat.status !== "free" || !sellable() || !state.mapReady;
      button.setAttribute("aria-pressed", String(chosen));
      const status = chosen ? "выбрано" : ({ free: "свободно", held: "временная бронь", selected: "временная бронь", occupied: "занято", unavailable: "недоступно" }[seat.status] || "недоступно");
      button.setAttribute("aria-label", `Ряд ${seat.row_number}, место ${seat.seat_number}, ${seat.seat_type === "vip" ? "VIP, " : seat.seat_type === "disabled" ? "МГН, " : ""}${money(cents(seat.price))}, ${status}`);
      button.title = button.getAttribute("aria-label");
      button.replaceChildren(document.createTextNode(chosen ? "✓" : ["occupied", "unavailable"].includes(seat.status) ? "×" : seat.seat_number));
      if (seat.seat_type === "vip") button.append(node("small", "", "V"));
      if (seat.seat_type === "disabled") button.append(node("small", "", "М"));
      if (["held", "selected"].includes(seat.status)) button.append(node("small", "", "Б"));
    });
  }
  function drawMap(data) {
    const grid = node("div", "seat-grid");
    grid.style.setProperty("--columns", data.seats_per_row);
    const indexed = new Map(state.seats.map(s => [`${s.row_number}:${s.seat_number}`, s]));
    for (let row = 1; row <= data.rows_count; row++) {
      grid.append(node("span", "row-label", row));
      for (let col = 1; col <= data.seats_per_row; col++) {
        const seat = indexed.get(`${row}:${col}`);
        if (!seat) { grid.append(node("span", "seat-hole")); continue; }
        const button = node("button", "seat"); button.type = "button";
        button.dataset.seatId = seat.id;
        button.addEventListener("click", () => toggleSeat(seat.id));
        grid.append(button);
      }
    }
    $("seat-map").replaceChildren(grid);
  }
  async function refreshMap() {
    if (!state.session || state.mapLoading || state.busy) return;
    const generation = state.generation;
    const sessionId = state.session.id;
    state.mapLoading = true;
    renderCart();
    try {
      const data = await api(`/api/v1/sessions/${sessionId}/seat-map/`);
      if (generation !== state.generation) return;
      state.clockOffset = new Date(data.server_time).getTime() - Date.now();
      const removed = [...state.selected].filter(id => !data.seats.some(s => s.id === id && s.status === "free"));
      removed.forEach(id => state.selected.delete(id));
      state.seats = data.seats;
      state.mapReady = true;
      if (!$("seat-map").querySelector(".seat-grid")) drawMap(data);
      updateSeatButtons();
      const available = data.seats.filter(s => s.status === "free").length;
      $("map-status").textContent = sellable() ? `Свободных мест: ${available}. Обновлено в ${time(data.server_time)}. Выбор мест не создаёт бронь до продажи.` : "Продажа закрыта: сеанс уже начался. Выберите другой сеанс.";
      if (removed.length) notice("Часть выбранных мест уже занята. Корзина обновлена — проверьте её перед оплатой.", "error");
    } catch (error) {
      if (generation !== state.generation) return;
      state.mapReady = false;
      $("map-status").textContent = "Схема не обновлена. Продажа приостановлена до восстановления связи.";
      showError(error); updateSeatButtons();
    } finally {
      if (generation === state.generation) { state.mapLoading = false; renderCart(); }
    }
  }
  function clearSession() {
    state.generation++; state.session = null; state.seats = []; state.selected.clear(); state.mapReady = false; state.mapLoading = false;
    $("movie-title").textContent = "Выберите сеанс слева";
    $("session-details").textContent = "Сначала фильм и время, затем — места.";
    $("seat-map").replaceChildren(node("p", "empty", "Здесь появятся свободные места"));
    $("map-status").textContent = "Места проверяются каждые 5 секунд. Выберите сеанс, чтобы загрузить схему.";
    renderCart();
  }
  function chooseSession(session) {
    if (state.busy || state.session?.id === session.id) return;
    clearSession(); state.session = session;
    $("movie-title").textContent = `${session.movie_title} · ${session.age_limit}+`;
    $("session-details").textContent = `${date(session.start_datetime)}, ${time(session.start_datetime)} · ${session.hall_name} · от ${money(cents(session.base_price))}`;
    $("seat-map").replaceChildren(node("p", "empty", "Загружаем схему зала…"));
    notice(); renderSessions(); renderCart(); refreshMap();
  }
  function renderSessions() {
    const query = $("session-search").value.trim().toLocaleLowerCase("ru");
    const items = state.sessions.filter(s => dateKey(s.start_datetime) === $("session-date").value && `${s.movie_title} ${s.hall_name}`.toLocaleLowerCase("ru").includes(query) && new Date(s.start_datetime).getTime() > now());
    const list = $("session-list"); list.replaceChildren();
    for (const session of items) {
      const button = node("button", "session-card"); button.type = "button";
      button.setAttribute("aria-pressed", String(state.session?.id === session.id));
      button.disabled = state.busy;
      button.append(node("span", "session-time", time(session.start_datetime)), node("span", "session-title", session.movie_title), node("span", "session-meta", `${session.hall_name} · ${session.age_limit}+ · от ${money(cents(session.base_price))}`));
      button.addEventListener("click", () => chooseSession(session)); list.append(button);
    }
    if (!items.length) list.append(node("p", "empty", state.sessions.length ? "Сеансы не найдены. Измените дату или поиск." : "Будущих сеансов нет. Добавьте расписание в разделе «Управление»."));
  }
  async function refreshSchedule() {
    if (state.busy) return;
    $("refresh-schedule").disabled = true;
    try {
      const data = await api(root.dataset.scheduleUrl);
      state.clockOffset = new Date(data.server_time).getTime() - Date.now();
      state.sessions = data.sessions;
      const previous = $("session-date").value;
      const dates = [...new Set(data.sessions.map(s => dateKey(s.start_datetime)))];
      $("session-date").replaceChildren(...dates.map(key => {
        const session = data.sessions.find(s => dateKey(s.start_datetime) === key);
        const option = node("option", "", date(session.start_datetime)); option.value = key; return option;
      }));
      if (dates.includes(previous)) $("session-date").value = previous;
      if (!dates.length) $("session-date").append(node("option", "", "Нет сеансов"));
      if (state.session) {
        const updated = data.sessions.find(s => s.id === state.session.id);
        if (!updated || updated.start_datetime !== state.session.start_datetime || updated.hall_name !== state.session.hall_name || updated.movie_title !== state.session.movie_title || updated.base_price !== state.session.base_price) {
          clearSession(); notice("Расписание изменилось. Выберите сеанс заново.", "error");
        }
      }
      renderSessions(); renderCart();
    } catch (error) { showError(error); }
    finally { $("refresh-schedule").disabled = state.busy; }
  }
  function showIssued(order) {
    const box = $("issued-details"); box.className = "issued-details"; box.replaceChildren();
    const info = node("p", "", `${order.tickets.length} бил. · ${money(cents(order.total_price))} · ${order.payment.method === "cash" ? "Наличные" : "Карта"} · учебная оплата`);
    const print = node("a", "button primary", "Открыть и распечатать");
    print.href = `/cashier/receipt/${order.id}/`; print.target = "_blank"; print.rel = "noopener";
    box.append(info, print);
    const tickets = $("issued-tickets"); tickets.replaceChildren();
    order.tickets.forEach(ticket => {
      const card = node("article", "issued-ticket");
      card.append(node("h3", "", `Ряд ${ticket.row_number} · Место ${ticket.seat_number}`), node("p", "small muted", `${ticket.movie_title} · ${date(ticket.start_datetime)}, ${time(ticket.start_datetime)} · ${ticket.hall_name}`));
      const img = document.createElement("img"); img.src = `/api/v1/tickets/${ticket.id}/download/?export=qr`; img.width = 150; img.height = 150; img.alt = `QR билета, ряд ${ticket.row_number}, место ${ticket.seat_number}`;
      const links = node("div", "ticket-links");
      for (const ext of ["pdf", "png"]) { const link = node("a", "", `Скачать ${ext.toUpperCase()}`); link.href = `/api/v1/tickets/${ticket.id}/download/?export=${ext}`; links.append(link); }
      card.append(img, links); tickets.append(card);
    });
    $("issued-sale").hidden = false; $("issued-sale").focus();
  }
  async function refreshHistory() {
    $("refresh-history").disabled = true;
    try {
      const data = await api(root.dataset.recentUrl); state.orders = data.orders;
      const list = $("recent-sales"); list.replaceChildren();
      for (const order of data.orders) {
        const row = node("div", "history-row"); const main = node("div", "history-main");
        const first = order.tickets[0];
        main.append(node("strong", "", first?.movie_title || "Продажа билетов"), node("span", "", `${date(order.created_at)}, ${time(order.created_at)} · ${order.tickets.length} бил. · ${order.id.slice(0, 8)}`));
        const amount = node("div", "history-amount", money(cents(order.total_price)));
        amount.append(node("small", "", order.payment?.method === "cash" ? "Наличные" : "Карта"));
        const button = node("button", "secondary", "Билеты"); button.type = "button"; button.addEventListener("click", () => showIssued(order));
        row.append(main, amount, button); list.append(row);
      }
      if (!data.orders.length) list.append(node("p", "empty", "У вас пока нет кассовых продаж. Оформите первую на схеме зала."));
    } catch (error) { $("recent-sales").replaceChildren(node("p", "empty", "Продажи не загружены. Нажмите «Обновить продажи».")); showError(error); }
    finally { $("refresh-history").disabled = false; }
  }
  async function sell(method) {
    if (state.busy || !state.selected.size || !state.mapReady || !sellable()) return;
    state.busy = true; const payload = { session_id: state.session.id, seat_ids: [...state.selected], method };
    notice("Оформляем продажу… Не закрывайте страницу."); renderCart(); updateSeatButtons();
    try {
      const order = await api("/api/v1/cashier/sales/", payload);
      state.selected.clear(); showIssued(order);
      notice("Продажа завершена. Билеты выданы. Реального списания денег нет.", "success");
    } catch (error) {
      if (error.uncertain) {
        state.selected.clear();
        notice("Ответ о продаже не получен. Перед новой попыткой проверьте «Мои последние продажи»: заказ мог уже сохраниться.", "error");
      } else showError(error);
    } finally {
      state.busy = false; state.mapReady = false; renderCart(); updateSeatButtons();
      await Promise.allSettled([refreshMap(), refreshHistory()]);
    }
  }
  function showView(checkin) {
    if (!state.busy) notice();
    $("sales-view").hidden = checkin; $("checkin-view").hidden = !checkin;
    $("show-sales").classList.toggle("active", !checkin); $("show-checkin").classList.toggle("active", checkin);
    $("show-sales").setAttribute("aria-pressed", String(!checkin)); $("show-checkin").setAttribute("aria-pressed", String(checkin));
    if (checkin) $("qr-payload").focus();
  }
  $("checkin-form").addEventListener("submit", async event => {
    event.preventDefault(); if ($("checkin-submit").disabled) return;
    const payload = $("qr-payload").value.trim(); if (!payload) return;
    $("checkin-submit").disabled = true;
    const result = $("checkin-result"); result.hidden = false; result.className = "notice"; result.textContent = "Проверяем билет…";
    try {
      const ticket = await api("/api/v1/cashier/check-in/", { payload });
      result.className = "notice success";
      result.textContent = `Вход разрешён и отмечен. ${ticket.movie_title} · ${ticket.hall_name} · ${date(ticket.start_datetime)}, ${time(ticket.start_datetime)} · Ряд ${ticket.row_number}, место ${ticket.seat_number}.`;
      $("qr-payload").value = "";
    } catch (error) { result.className = "notice error"; result.textContent = error.uncertain ? "Ответ не получен. Вход мог быть уже отмечен. Проверьте билет повторно и уточните его статус." : error.message; if (error.auth) showError(error); }
    finally { $("checkin-submit").disabled = false; $("qr-payload").focus(); $("qr-payload").select(); }
  });
  $("show-sales").addEventListener("click", () => showView(false));
  $("show-checkin").addEventListener("click", () => showView(true));
  $("pay-cash").addEventListener("click", () => sell("cash"));
  $("pay-card").addEventListener("click", () => sell("card"));
  $("clear-selection").addEventListener("click", () => { if (!state.busy) { state.selected.clear(); updateSeatButtons(); renderCart(); } });
  $("session-date").addEventListener("change", () => { if (!state.busy) { clearSession(); renderSessions(); } });
  $("session-search").addEventListener("input", renderSessions);
  $("refresh-map").addEventListener("click", refreshMap);
  $("refresh-schedule").addEventListener("click", refreshSchedule);
  $("refresh-history").addEventListener("click", refreshHistory);
  $("close-issued").addEventListener("click", () => { $("issued-sale").hidden = true; $("show-sales").focus(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshMap(); });
  setInterval(() => { if (!document.hidden && !$("sales-view").hidden) refreshMap(); }, 5000);
  setInterval(() => { if (!document.hidden && !state.busy) refreshSchedule(); }, 60000);
  Promise.allSettled([refreshSchedule(), refreshHistory()]);
})();
