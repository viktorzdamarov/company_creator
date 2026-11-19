/* Campaign editor page. */
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

  function load() {
    if (!campaignId) return;
    $("#loading").prop("hidden", false);
    A.api("GET", "/api/campaigns/" + campaignId)
      .done(function (c) { $flash.prop("hidden", true); render(c); })
      .fail(function (xhr) { $card.prop("hidden", true); flash(A.errorText(xhr), "error"); })
      .always(function () { $("#loading").prop("hidden", true); });
  }

  function sharesText(stream) {
    return stream.offers.map(function (o) { return o.share + "%"; }).join(" / ");
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

  function renderStream(s) {
    var html = '<tr class="flow' + (s.state !== "active" ? " off" : "") + '" data-stream="' + s.id + '"><td>';
    html += '<div class="flow-title"><span class="dot"></span>Flow ' + s.position +
      ' <span class="muted">· ' + esc(s.name) + "</span></div>";
    if (!s.editable) html += '<div class="flow-action">' + esc(s.action) + "</div>";
    if (s.filters.length) {
      html += '<div class="flow-sub">Фильтры</div><ul class="filters">' +
        s.filters.map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + "</ul>";
    }
    if (s.editable) {
      html += '<div class="flow-sub">Офферы</div><ul class="offers">';
      s.offers.forEach(function (o) {
        var last = s.offers.length === 1;
        html += '<li><span class="offer-name">[' + o.offer_id + "] " + esc(o.name) + "</span>" +
          '<span class="share">' + o.share + "%</span>" +
          '<button type="button" class="btn-x remove-offer" data-offer="' + o.offer_id + '"' +
          (last ? ' disabled title="Нельзя удалить последний оффер потока"' : ' title="Удалить оффер"') + ">×</button></li>";
      });
      html += "</ul>";
      html += '<div class="add-offer"><div class="ac grow" data-source="/api/offers">' +
        '<input class="ac-input" placeholder="Добавить оффер: ID или название">' +
        '<input type="hidden" class="ac-value"><ul class="ac-list" hidden></ul></div>' +
        '<button type="button" class="btn btn-primary add-btn">Добавить</button></div>';
    }
    html += "</td>";
    html += '<td class="num">' + s.clicks + '</td><td class="num">' + s.unique_clicks + '</td><td class="num">' + s.bots + "</td></tr>";
    return $(html);
  }

  function change(method, url, data, okMsg) {
    if (busy) return;
    setBusy(true);
    A.api(method, url, data)
      .done(function (c) {
        render(c);
        var s = c.streams.find(function (x) { return x.editable; });
        flash(okMsg + (s ? ". Проценты: " + sharesText(s) : ""), "ok");
      })
      .fail(function (xhr) { flash(A.errorText(xhr), "error"); })
      .always(function () { setBusy(false); });
  }

  $flows.on("click", ".add-btn", function () {
    var $row = $(this).closest("tr"), streamId = $row.data("stream");
    var offerId = $row.find(".ac").data("widget").value();
    if (!offerId) return flash("Выберите оффер из списка (или введите его ID)", "error");
    change("POST", "/api/campaigns/" + campaignId + "/streams/" + streamId + "/offers",
      { offer_id: offerId }, "Оффер " + offerId + " добавлен");
  });

  $flows.on("click", ".remove-offer", function () {
    var $row = $(this).closest("tr"), streamId = $row.data("stream"), offerId = $(this).data("offer");
    if (!confirm("Удалить оффер " + offerId + " из потока? Проценты пересчитаются поровну.")) return;
    change("DELETE", "/api/campaigns/" + campaignId + "/streams/" + streamId + "/offers/" + offerId,
      null, "Оффер " + offerId + " удалён");
  });

  $("#reload").on("click", load);
  window.addEventListener("popstate", function (e) { if (e.state && e.state.id) { campaignId = e.state.id; load(); } });

  if (campaignId) { history.replaceState({ id: campaignId }, "", "/edit/" + campaignId); load(); }
});
