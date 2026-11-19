"""Read-only smoke check against the real Keitaro configured in .env.

Usage:  python -m scripts.keitaro_smoke [campaign_id]

Does NOT create or modify anything. Never prints the API key.
"""
import sys

from app.core.config import get_settings
from app.keitaro import KeitaroClient, KeitaroError
from app.services.defaults import resolve_defaults


def main() -> int:
    settings = get_settings()
    print(f"Keitaro: {settings.keitaro_url}")
    with KeitaroClient.from_settings(settings) as kc:
        try:
            domains = kc.list_domains()
            groups = kc.list_campaign_groups()
            sources = kc.list_traffic_sources()
            offers = kc.list_offers()
            campaigns = kc.list_campaigns()
        except KeitaroError as exc:
            print(f"FAIL: {exc}")
            return 1

        print(f"domains ({len(domains)}): {', '.join(d.name for d in domains)}")
        print(f"campaign groups ({len(groups)}): {', '.join(g.name for g in groups[:10])}{' ...' if len(groups) > 10 else ''}")
        print(f"traffic sources ({len(sources)}): {', '.join(s.name for s in sources)}")
        print(f"offers ({len(offers)}): " + "; ".join(f"[{o.id}] {o.name}" for o in offers[:5]))
        print(f"campaigns: {len(campaigns)}")

        try:
            d = resolve_defaults(
                kc, settings.keitaro_default_domain, settings.keitaro_default_group, settings.keitaro_default_source
            )
            print(f"defaults OK: domain={d.domain.name}#{d.domain.id} group={d.group.name}#{d.group.id} "
                  f"source={d.traffic_source.name}#{d.traffic_source.id}")
        except KeitaroError as exc:
            print(f"defaults FAIL: {exc}")
            return 1

        if len(sys.argv) > 1:
            cid = int(sys.argv[1])
            c = kc.get_campaign(cid)
            stats = kc.stream_stats(cid)
            print(f"\ncampaign #{c.id} {c.name}  {c.tracking_url}")
            for s in kc.get_streams(cid):
                st = stats.get(s.id)
                print(f"  stream #{s.id} pos={s.position} type={s.type} schema={s.schema_} "
                      f"action={s.action_type}:{s.action_payload or ''} "
                      f"filters={[(f.name, f.mode, f.payload) for f in s.filters]} "
                      f"offers={[(o.offer_id, o.share) for o in s.offers]} "
                      f"clicks={st.clicks if st else 0} uniq={st.unique_clicks if st else 0} bots={st.bots if st else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
