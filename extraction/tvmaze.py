import os
import re
import time
import requests
import pandas as pd

RATE_LIMIT_DELAY = 0.55

BROADCAST_NETWORKS = {
    "ABC", "CBS", "NBC", "FOX", "The CW", "CW", "PBS",
    "BBC One", "BBC Two", "ITV", "ITV1", "Channel 4", "Channel 5",
    "Global", "CTV", "CBC", "Network 10", "Nine Network", "Seven Network"
}


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    return re.sub(r"<[^>]+>", "", raw_html).strip()


def get_channel_info(show_data: dict) -> tuple[str, str, str]:
    web_channel = show_data.get("webChannel")
    network = show_data.get("network")

    if web_channel:
        name = web_channel.get("name") or "Unknown Streaming"
        country = (web_channel.get("country") or {}).get("code") or "Global"
        return name, "Streaming", country

    if network:
        name = network.get("name") or "Unknown Network"
        country = (network.get("country") or {}).get("code") or "Unknown"
        channel_type = "Broadcast" if name in BROADCAST_NETWORKS else "Cable"
        return name, channel_type, country

    return "Unknown", "Unknown", "Unknown"


def classify_format_and_ip(show_type: str, genres: list[str], summary: str) -> tuple[str, str, str]:
    genre_set = set(genres)
    summary_lower = summary.lower()

    if show_type in {"Reality", "Game Show", "Variety"} or "Reality" in genre_set:
        format_label = show_type
    elif show_type == "Animation":
        format_label = "Scripted (Animation)"
    else:
        if any(w in summary_lower for w in ["anthology"]):
            structure = "Anthology"
        elif any(w in summary_lower for w in ["each week", "each episode", "case of the week", "procedural", "detective", "investigate"]):
            structure = "Procedural"
        elif genre_set & {"Crime", "Mystery", "Comedy"} and not (genre_set & {"Science-Fiction", "Fantasy"}):
            structure = "Procedural"
        else:
            structure = "Serialized"
        format_label = f"{show_type} ({structure})"

    adaptation_markers = [
        "based on", "adapted from", "adaptation of", "novel by", "book by",
        "comic book", "graphic novel", "manga", "true story", "video game"
    ]
    origin_type = "Adaptation / IP" if any(m in summary_lower for m in adaptation_markers) else "Original"

    ip_flags = []
    if any(k in summary_lower for k in ["spin-off", "spinoff", "spin off"]):
        ip_flags.append("Spin-off")
    if any(k in summary_lower for k in ["reboot", "revival", "remake", "reimagining"]):
        ip_flags.append("Reboot/Revival")
    if origin_type == "Adaptation / IP":
        ip_flags.append("Based on Known Story/IP")

    ip_detail = ", ".join(ip_flags) if ip_flags else "None Detected"
    return format_label, origin_type, ip_detail


def safe_get(url: str, max_retries: int = 5) -> requests.Response | None:
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                return resp
            if resp.status_code == 429:
                wait_time = 10 + attempt * 5
                print(f" [RATE LIMIT 429] Sleeping {wait_time}s...")
                time.sleep(wait_time)
                continue
        except requests.RequestException as e:
            print(f" [NETWORK ERROR] {e}. Retrying...")
            time.sleep(3)
    return None


def fetch_all_base_shows(
    start_year: int | None = None,
    end_year: int | None = None,
    require_imdb: bool = False,
    max_index_pages: int = 350,
) -> list[dict]:
    print("=== STAGE 1: Crawling TVmaze Master Show Index ===")
    candidate_shows = []
    page = 0

    while page <= max_index_pages:
        url = f"https://api.tvmaze.com/shows?page={page}"
        resp = safe_get(url)

        if not resp or resp.status_code == 404:
            print(f"[STAGE 1 COMPLETE] Reached end of TVmaze index at page {page}.")
            break

        shows = resp.json()
        if not shows:
            break

        for show in shows:
            show_type = show.get("type") or ""
            genres = show.get("genres") or []
            if show_type in {"Documentary", "Talk Show", "News", "Sports"} or "Documentary" in genres:
                continue

            imdb_id = (show.get("externals") or {}).get("imdb")
            if require_imdb and not imdb_id:
                continue

            premiered = show.get("premiered") or ""
            prem_year = int(premiered.split("-")[0]) if premiered and premiered[:4].isdigit() else None

            if start_year and (not prem_year or prem_year < start_year):
                continue
            if end_year and (not prem_year or prem_year > end_year):
                continue

            candidate_shows.append(show)

        print(f" -> Indexed Page {page} | Qualifying Shows So Far: {len(candidate_shows)}")
        page += 1
        time.sleep(RATE_LIMIT_DELAY)

    return candidate_shows


def enrich_show_details(tvmaze_id: int) -> dict | None:
    url = (
        f"https://api.tvmaze.com/shows/{tvmaze_id}"
        f"?embed[]=episodes&embed[]=cast&embed[]=crew"
    )
    resp = safe_get(url)
    if not resp or resp.status_code != 200:
        return None

    data = resp.json()
    embedded = data.get("_embedded") or {}

    episodes = embedded.get("episodes") or []
    num_episodes = len(episodes)
    season_numbers = {ep.get("season") for ep in episodes if ep.get("season")}
    num_seasons = len(season_numbers)
    season_length = round(num_episodes / num_seasons, 2) if num_seasons > 0 else 0.0

    cast = embedded.get("cast") or []
    lead_actors_list = []
    for member in cast[:5]:
        person_name = (member.get("person") or {}).get("name")
        if person_name and person_name not in lead_actors_list:
            lead_actors_list.append(person_name)
    lead_actors = ", ".join(lead_actors_list) if lead_actors_list else "Unknown"

    crew = embedded.get("crew") or []
    creators_list = [
        (c.get("person") or {}).get("name")
        for c in crew
        if c.get("type") in {"Creator", "Developer"} and (c.get("person") or {}).get("name")
    ]
    creators = ", ".join(dict.fromkeys(creators_list)) if creators_list else "Unknown"

    status = data.get("status") or "Unknown"
    if num_seasons > 1 or (num_seasons == 1 and status == "Running"):
        target_renewed = 1
    else:
        target_renewed = 0

    primary_network, channel_type, country = get_channel_info(data)
    premiered = data.get("premiered") or ""
    parts = premiered.split("-")
    premiere_year = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else None
    premiere_month = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None

    genres = data.get("genres") or []
    show_type = data.get("type") or "Unknown"
    summary_clean = clean_html(data.get("summary") or "")
    format_label, origin_type, ip_detail = classify_format_and_ip(show_type, genres, summary_clean)

    schedule = data.get("schedule") or {}
    schedule_days = ", ".join(schedule.get("days") or []) or "Unknown"
    schedule_time = schedule.get("time") or "Unknown"

    externals = data.get("externals") or {}

    return {
        "status": status,
        "target_renewed": target_renewed,
        "primary_network": primary_network,
        "channel_type": channel_type,
        "tvmaze_weight_popularity": data.get("weight"),
        "audience_score": (data.get("rating") or {}).get("average"),
        "lead_actors": lead_actors,
        "creators": creators,
        "genre": ", ".join(genres),
        "format": format_label,
        "num_seasons": num_seasons,
        "num_episodes": num_episodes,
        "season_length": season_length,
        "premiere_year": premiere_year,
        "premiere_month": premiere_month,
        "schedule_days": schedule_days,
        "schedule_time": schedule_time,
        "runtime": data.get("averageRuntime") or data.get("runtime"),
        "original_vs_adaptation": origin_type,
        "ip_spin_off_reboot_story": ip_detail,
        "language": data.get("language"),
        "country": country,
        "title": data.get("name") or "Unknown",
        "imdb_id": externals.get("imdb"),
        "thetvdb_id": externals.get("thetvdb"),
        "tvmaze_id": data.get("id"),
        "summary": summary_clean,
    }


def build_tvmaze_dataset(
    start_year: int | None = 2010,
    end_year: int | None = 2024,
    require_imdb: bool = True,
    output_csv: str = "tvmaze_tv_dataset.csv",
) -> pd.DataFrame:
    existing_ids = set()
    rows = []

    if os.path.exists(output_csv):
        existing_df = pd.read_csv(output_csv)
        rows = existing_df.to_dict("records")
        existing_ids = set(existing_df["tvmaze_id"].dropna().astype(int))
        print(f"[INFO] Resuming: Loaded {len(existing_ids)} already-scraped shows from {output_csv}")

    candidates = fetch_all_base_shows(
        start_year=start_year,
        end_year=end_year,
        require_imdb=require_imdb,
    )
    remaining = [s for s in candidates if s.get("id") not in existing_ids]
    print(f"\n=== STAGE 2: Enriching {len(remaining)} Shows (Cast, Crew, Seasons, Episodes) ===")

    for idx, show in enumerate(remaining, start=1):
        tvmaze_id = show.get("id")
        title = show.get("name", "Unknown")

        enriched = enrich_show_details(tvmaze_id)
        time.sleep(RATE_LIMIT_DELAY)

        if not enriched:
            continue

        rows.append(enriched)
        existing_ids.add(tvmaze_id)

        print(f" [{idx}/{len(remaining)}] Processed: '{title}' (IMDb: {enriched['imdb_id']}) | Status: {enriched['status']}")

        if len(rows) % 100 == 0:
            pd.DataFrame(rows).to_csv(output_csv, index=False)
            print(f" [CHECKPOINT] Saved {len(rows)} shows to {output_csv}")

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    print(f"\n[FINISHED] Saved {len(df)} total shows to {output_csv}!")
    return df


if __name__ == "__main__":
    df_tvmaze = build_tvmaze_dataset(
        start_year=2010,
        end_year=2024,
        require_imdb=True,
        output_csv="tvmaze_tv_dataset.csv"
    )