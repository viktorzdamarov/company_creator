/* Campaign editor page: local draft of flows/offers, published to Keitaro with Push. */
$(function () {
  "use strict";
  var A = window.Adrobot, esc = A.esc;
  var $card = $("#campaign"), $flows = $("#flows"), $flash = $("#flash");
  var campaignId = parseInt($card.data("campaign-id"), 10) || null;
  var busy = false;

  A.autocomplete($(".ac[data-source='/api/campaigns']"), {
    onSelect: function (c) { open(c.id, true); },
  });

  function flash(msg, kind) {
    $flash.removeClass("alert-error alert-ok").addClass(kind === "error" ? "alert-error" : "alert-ok")
      .text(msg).prop("hidden", false);
  }

  function setBusy(on) {
    busy = on;
    $card.toggleClass("busy", on);
    $card.find("button, input").prop("disabled", on);
  }

  function open(id, push) {
    campaignId = id;
    if (push) history.pushState({ id: id }, "", "/edit/" + id);
    load();
  }

  /** Open: show the local copy; if the campaign was never fetched, fetch it from Keitaro. */
  function load() {
    if (!campaignId) return;
    $("#loading").prop("hidden", false);
    A.api("GET", "/api/campaigns/" + campaignId)
      .done(function (c) { $flash.prop("hidden", true); render(c); $("#loading").prop("hidden", true); })
      .fail(function (xhr) {
        if (xhr.status === 404 && xhr.responseJSON && xhr.responseJSON.error === "CampaignNotFetchedError") {
          fetchStreams();
        } else {
          $card.prop("hidden", true);
          flash(A.errorText(xhr), "error");
          $("#loading").prop("hidden", true);
        }
      });
  }

  function fetchStreams() {
    if (busy) return;
    var visible = !$card.prop("hidden");
    $("#loading").prop("hidden", false);
    if (visible) setBusy(true);
    A.api("POST", "/api/campaigns/" + campaignId + "/fetch")
      .done(function (c) { render(c); flash("Потоки загружены из Keitaro", "ok"); })
      .fail(function (xhr) { $card.prop("hidden", !visible); flash(A.errorText(xhr), "error"); })
      .always(function () { if (visible) setBusy(false); $("#loading").prop("hidden", true); });
  }

  function render(c) {
    $("#c-name").text(c.name);
    $("#c-id").text(c.id);
    $("#c-group").text(c.group || "без группы");
    $("#c-url").text(c.tracking_url || "");
    $("#t-clicks").text(c.total_clicks);
    $("#t-uniq").text(c.total_unique_clicks);
    $("#t-bots").text(c.total_bots);
    $("#campaign-search").val(c.name);

    $flows.empty();
    c.streams.forEach(function (s) { $flows.append(renderStream(s)); });
    $flows.find(".ac").each(function () {
      var $ac = $(this);
      $ac.data("widget", A.autocomplete($ac));
    });
    $card.prop("hidden", false);
  }

  function renderOffer(o) {
    var grey = o.status === "removing" || o.status === "removed";
    var html = '<li class="' + (grey ? "grey " : "") + o.status + '" data-offer="' + o.offer_id + '">' +
      '<span class="offer-name">[' + o.offer_id + "] " + esc(o.name) + "</span>";
    if (o.status === "removed") html += '<span class="tag">removed</span>';
    if (o.status === "removing") html += '<span class="tag">будет удалён</span>';
    html += '<span class="share">' + o.share + "%</span>";
    if (grey) {
      html += '<button type="button" class="btn btn-sm bring-back">Bring back</button>';
    } else {
      html += '<button type="button" class="btn-pin pin' + (o.pinned ? " on" : "") + '" title="' +
        (o.pinned ? "Открепить долю" : "Закрепить долю") + '">📌</button>' +
        '<button type="button" class="btn-x remove-offer" title="Удалить оффер">×</button>';
    }
    return html + "</li>";
  }

  function renderStream(s) {
    var html = '<tr class="flow' + (s.dirty ? " dirty" : "") + '" data-stream="' + s.id + '"><td>';
    html += '<div class="flow-title"><span class="dot"></span>Flow ' + s.position +
      ' <span class="muted">· ' + esc(s.name) + "</span></div>";
    if (!s.has_offers) {
      html += '<div class="flow-note">Поток без офферов</div>';
    } else {
      if (s.dirty) html += '<div class="flow-note">Не опубликован: изменения только здесь, в Keitaro их ещё нет</div>';
      var live = s.offers.filter(function (o) { return o.status === "active" || o.status === "new"; });
      var gone = s.offers.filter(function (o) { return o.status === "removing" || o.status === "removed"; });
      html += '<div class="flow-sub">Офферы</div><ul class="offers">' +
        live.concat(gone).map(renderOffer).join("") + "</ul>";
      html += '<div class="add-offer"><div class="ac grow" data-source="/api/offers">' +
        '<input class="ac-input" placeholder="Добавить оффер: ID или название">' +
        '<input type="hidden" class="ac-value"><ul class="ac-list" hidden></ul></div>' +
        '<button type="button" class="btn add-btn">Добавить</button></div>';
      html += '<div class="flow-actions">' +
        '<button type="button" class="btn btn-primary push-btn"' + (s.dirty ? "" : " disabled") + ">Push</button>" +
        '<button type="button" class="btn cancel-btn"' + (s.dirty ? "" : " disabled") + ">Cancel</button></div>";
    }
    html += "</td>";
    html += '<td class="num">' + s.clicks + '</td><td class="num">' + s.unique_clicks + '</td><td class="num">' + s.bots + "</td></tr>";
    return $(html);
  }

  function change(method, url, data, okMsg) {
    if (busy) return;
    setBusy(true);
    A.api(method, url, data)
      .done(function (c) { render(c); flash(okMsg, "ok"); })
      .fail(function (xhr) { flash(A.errorText(xhr), "error"); })
      .always(function () { setBusy(false); });
  }

  function streamUrl($el) {
    return "/api/campaigns/" + campaignId + "/streams/" + $el.closest("tr").data("stream");
  }

  $flows.on("click", ".add-btn", function () {
    var $row = $(this).closest("tr");
    var offerId = $row.find(".ac").data("widget").value();
    if (!offerId) return flash("Выберите оффер из списка (или введите его ID)", "error");
    change("POST", streamUrl($(this)) + "/offers", { offer_id: offerId },
      "Оффер " + offerId + " добавлен локально. Нажмите Push, чтобы опубликовать в Keitaro");
  });

  $flows.on("click", ".remove-offer", function () {
    var offerId = $(this).closest("li").data("offer");
    change("DELETE", streamUrl($(this)) + "/offers/" + offerId, null,
      "Оффер " + offerId + " помечен удалённым. Нажмите Push, чтобы убрать его из Keitaro");
  });

  $flows.on("click", ".bring-back", function () {
    var offerId = $(this).closest("li").data("offer");
    change("POST", streamUrl($(this)) + "/offers/" + offerId + "/bring-back", null, "Оффер " + offerId + " возвращён");
  });

  $flows.on("click", ".pin", function () {
    var offerId = $(this).closest("li").data("offer"), on = !$(this).hasClass("on");
    change("PUT", streamUrl($(this)) + "/offers/" + offerId + "/pin", { pinned: on },
      on ? "Доля оффера " + offerId + " закреплена" : "Доля оффера " + offerId + " откреплена");
  });

  $flows.on("click", ".push-btn", function () {
    change("POST", streamUrl($(this)) + "/push", null, "Опубликовано в Keitaro");
  });

  $flows.on("click", ".cancel-btn", function () {
    if (!confirm("Отменить неопубликованные изменения потока?")) return;
    change("POST", streamUrl($(this)) + "/cancel", null, "Изменения отменены");
  });

  $("#reload").on("click", fetchStreams);
  window.addEventListener("popstate", function (e) { if (e.state && e.state.id) { campaignId = e.state.id; load(); } });

  if (campaignId) { history.replaceState({ id: campaignId }, "", "/edit/" + campaignId); load(); }
});
