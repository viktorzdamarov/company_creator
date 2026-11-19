/* New campaign page. */
$(function () {
  "use strict";
  var A = window.Adrobot;
  var offer = A.autocomplete($("#create-form .ac"));
  var $btn = $("#create-btn"), $err = $("#create-error");

  function showError(msg) { $err.text(msg).prop("hidden", false); }

  $("#create-form").on("submit", function (e) {
    e.preventDefault();
    $err.prop("hidden", true);

    var name = $("#name").val().trim();
    var geo = $("#geo").val().trim();
    var offerId = offer.value();
    var dry = $("#dry_run").is(":checked");
    if (!name) return showError("Укажите название кампании");
    if (!geo) return showError("Укажите хотя бы одну страну, например AU");
    if (!offerId) return showError("Выберите оффер из списка (или введите его ID)");

    $btn.prop("disabled", true).text(dry ? "Проверка…" : "Создание…");
    A.api("POST", "/api/campaigns" + (dry ? "?dry_run=true" : ""), { name: name, geo: geo, offer_id: offerId })
      .done(function (r) { renderResult(r); if (!r.dry_run) { $("#create-form")[0].reset(); offer.reset(); } })
      .fail(function (xhr) { showError(A.errorText(xhr)); })
      .always(function () { $btn.prop("disabled", false).text("Create"); });
  });

  function renderResult(r) {
    $("#result-title").text(r.dry_run ? "Предпросмотр: ничего не создано" : "Кампания создана");
    $("#result").toggleClass("dry", r.dry_run);
    $("#r-id").text(r.campaign_id || "—");
    $("#r-name").text(r.name);
    $("#r-url").text(r.tracking_url);
    $("#r-defaults").text(r.domain + " / " + r.group + " / " + r.traffic_source);
    $("#r-time").text((r.elapsed_ms / 1000).toFixed(1) + " с");
    var $s = $("#r-streams").empty();
    r.streams.forEach(function (s) {
      $("<li>").append($("<b>").text("Flow " + s.position + ": "), document.createTextNode(s.description)).appendTo($s);
    });
    if (r.campaign_id) $("#r-edit").attr("href", "/edit/" + r.campaign_id).prop("hidden", false);
    else $("#r-edit").prop("hidden", true);
    if (r.payloads) $("#r-payloads").prop("hidden", false).find("pre").text(JSON.stringify(r.payloads, null, 2));
    else $("#r-payloads").prop("hidden", true);
    $("#result").prop("hidden", false);
  }

  $("#copy-url").on("click", function () { A.copy($("#r-url").text(), $(this)); });
});
