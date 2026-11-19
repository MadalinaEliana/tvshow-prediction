import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")
OMDb_DAILY_LIMIT = 100000

BROADCAST_NETWORKS = {
    "ABC", "CBS", "NBC", "FOX", "The CW", "CW", "PBS",
    "BBC One", "BBC Two", "ITV", "Channel 4", "Channel 5",
    "Global", "CTV", "CBC", "Network 10", "Nine Network", "Seven Network"
}

STREAMING_NETWORKS = {
    "Netflix", "Prime Video", "Amazon", "Hulu", "Disney+", "Max",
    "HBO Max", "Apple TV+", "Peacock", "Paramount+", "YouTube",
    "Discovery+", "ESPN+", "BritBox", "Acorn TV", "Shudder",
    "Roku Channel", "Viki", "Crunchyroll", "U-NEXT", "TVING"
}


def classify_channel_type(primary_network: str) -> str:
    if not primary_network or primary_network == "Unknown":
        return "Unknown"
    if primary_network in STREAMING_NETWORKS:
        return "Streaming"
    if primary_network in BROADCAST_NETWORKS:
        return "Broadcast"
    lowered = primary_network.lower()
    if any(tag in lowered for tag in ["+", "plus", "netflix", "prime", "hulu", "peacock", "paramount"]):
        return "Streaming"
    return "Cable"


def classify_format(show_type: str, genres: list[str], keywords: list[str]) -> str:
    kw_text = " ".join(keywords).lower()
    genre_set = set(genres)

    if show_type == "Reality" or "Reality" in genre_set:
        return "Reality"
    if show_type == "Talk Show" or "Talk" in genre_set:
        return "Talk Show"

    style = "Scripted" if (
        show_type in {"Scripted", "Miniseries"}
        or bool(genre_set & {"Drama", "Comedy", "Sci-Fi & Fantasy", "Crime", "Mystery", "Action & Adventure"})
    ) else "Other"

    if "anthology" in kw_text:
        structure = "Anthology"
    elif any(term in kw_text for term in ["procedural", "police procedural", "medical drama", "case of the week"]):
        structure = "Procedural"
    elif any(term in kw_text for term in ["serialized", "story arc", "continuous storyline"]):
        structure = "Serialized"
    else:
        if genre_set & {"Crime", "Mystery", "Action & Adventure", "Comedy"} and not (genre_set & {"Sci-Fi & Fantasy"}):
            structure = "Procedural"
        elif genre_set & {"Drama", "Sci-Fi & Fantasy"}:
            structure = "Serialized"
        else:
            structure = "Mixed/Unspecified"

    return f"{style} ({structure})"


def classify_origin_and_ip(show_type: str, keywords: list[str], overview: str) -> tuple[str, str]:
    kw_text = " ".join(keywords).lower()
    ov_text = (overview or "").lower()
    combined = f"{kw_text} {ov_text}"

    adaptation_markers = [
        "based on novel", "based on book", "based on comic", "based on graphic novel",
        "based on manga", "based on anime", "based on video game", "based on true story",
        "based on play", "based on short story", "adaptation", "based on"
    ]
    origin_type = "Adaptation / IP" if (show_type == "Miniseries" or any(m in combined for m in adaptation_markers)) else "Original"

    ip_flags = []
    if any(k in kw_text for k in ["spin off", "spinoff", "spin-off"]):
        ip_flags.append("Spin-off")
    if any(k in kw_text for k in ["reboot", "revival", "remake"]):
        ip_flags.append("Reboot/Revival")
    if any(k in combined for k in adaptation_markers):
        ip_flags.append("Based on Known Story/IP")

    return origin_type, (", ".join(ip_flags) if ip_flags else "None Detected")


def get_tmdb_details(tv_id: int) -> dict | None:
    url = (
        f"https://api.themoviedb.org/3/tv/{tv_id}"
        f"?api_key={TMDB_API_KEY}&language=en-US"
        f"&append_to_response=credits,keywords,external_ids"
    )
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return None

    data = resp.json()
    show_type = data.get("type", "") or ""
    genres = [g.get("name", "") for g in data.get("genres", []) if g.get("name")]
    if show_type in {"Documentary", "Talk Show"} or "Documentary" in genres:
        return None

    imdb_id = (data.get("external_ids") or {}).get("imdb_id")
    if not imdb_id:
        return None

    networks = data.get("networks") or []
    primary_network = networks[0].get("name", "Unknown") if networks else "Unknown"
    channel_type = classify_channel_type(primary_network)

    num_seasons = int(data.get("number_of_seasons") or 0)
    num_episodes = int(data.get("number_of_episodes") or 0)
    season_length = round(num_episodes / num_seasons, 2) if num_seasons > 0 else 0.0

    first_air_date = data.get("first_air_date") or ""
    parts = first_air_date.split("-")
    premiere_year = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else None
    premiere_month = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None

    keywords = [k.get("name", "") for k in (data.get("keywords", {}).get("results") or []) if k.get("name")]
    overview = data.get("overview") or ""
    format_label = classify_format(show_type, genres, keywords)
    origin_type, ip_detail = classify_origin_and_ip(show_type, keywords, overview)

    credits = data.get("credits") or {}
    sorted_cast = sorted(credits.get("cast", []), key=lambda x: x.get("order", 999))
    lead_actors = ", ".join(m.get("name") for m in sorted_cast[:5] if m.get("name")) or "Unknown"

    creators = ", ".join(c.get("name") for c in (data.get("created_by") or []) if c.get("name")) or "Unknown"
    status = data.get("status") or "Unknown"

    if num_seasons > 1 or (num_seasons == 1 and status == "Returning Series"):
        target_renewed = 1
    else:
        target_renewed = 0

    return {
        "tmdb_id": tv_id,
        "imdb_id": imdb_id,
        "title": data.get("name") or "Unknown",
        "status": status,
        "target_renewed": target_renewed,
        "primary_network": primary_network,
        "channel_type": channel_type,
        "popularity_votes": data.get("vote_count"),
        "popularity_score": data.get("popularity"),
        "audience_score": data.get("vote_average"),
        "lead_actors": lead_actors,
        "genre": ", ".join(genres),
        "format": format_label,
        "num_seasons": num_seasons,
        "num_episodes": num_episodes,
        "season_length": season_length,
        "premiere_year": premiere_year,
        "premiere_month": premiere_month,
        "original_vs_adaptation": origin_type,
        "ip_spin_off_reboot_story": ip_detail,
        "creators": creators,
    }


def get_omdb_details(imdb_id: str) -> dict:
    url = (
        f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}"
        f"&i={imdb_id}&type=series&plot=full&tomatoes=true"
    )
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return {}

    payload = resp.json()
    if payload.get("Response") != "True":
        return {}

    # Extract Rotten Tomatoes score from Ratings array if present
    rt_score = None
    for rating in payload.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            rt_score = rating.get("Value")
            break

    return {
        "omdb_genre": payload.get("Genre"),
        "omdb_actors": payload.get("Actors"),
        "omdb_writer": payload.get("Writer"),
        "omdb_director": payload.get("Director"),
        "omdb_plot": payload.get("Plot"),
        "omdb_awards": payload.get("Awards"),
        "omdb_runtime": payload.get("Runtime"),
        "omdb_rated": payload.get("Rated"),
        "omdb_total_seasons": payload.get("totalSeasons"),
        "imdb_rating": payload.get("imdbRating"),
        "imdb_votes": payload.get("imdbVotes"),
        "metascore": payload.get("Metascore"),
        "rotten_tomatoes_score": rt_score,
        "tomato_meter": payload.get("tomatoMeter"),
        "tomato_user_meter": payload.get("tomatoUserMeter"),
        "tomato_consensus": payload.get("tomatoConsensus"),
    }


def build_linked_dataset(
    start_year: int = 2018,
    end_year: int = 2026,
    output_csv: str = "tmdb_omdb_tv_renewal.csv",
    omdb_calls_today: int = 0,
) -> pd.DataFrame:
    existing_ids = set()
    rows = []

    if os.path.exists(output_csv):
        existing_df = pd.read_csv(output_csv)
        rows = existing_df.to_dict("records")
        existing_ids = set(existing_df["tmdb_id"].dropna().astype(int))
        print(f"[INFO] Loaded {len(existing_ids)} existing shows from {output_csv}")

    for year in range(start_year, end_year + 1):
        page = 1
        total_pages = 500
        print(f"   STARTING YEAR: {year} ")

        while page <= total_pages and page <= 500:
            discover_url = (
                f"https://api.themoviedb.org/3/discover/tv"
                f"?api_key={TMDB_API_KEY}&language=en-US"
                f"&sort_by=popularity.desc&with_original_language=en"
                f"&without_genres=99,10767"
                f"&with_status=0|3|4"
                f"&first_air_date_year={year}"
                f"&page={page}"
            )
            resp = requests.get(discover_url, timeout=15)
            if resp.status_code != 200:
                print(f"[ERROR] TMDb API failed on Year {year}, Page {page}. Moving to next year.")
                break

            payload = resp.json()
            total_pages = min(int(payload.get("total_pages") or 1), 500)

            for item in payload.get("results", []):
                tv_id = item.get("id")
                if not tv_id or tv_id in existing_ids:
                    continue

                tmdb_row = get_tmdb_details(tv_id)
                time.sleep(0.1)
                if not tmdb_row:
                    continue

                if omdb_calls_today >= OMDb_DAILY_LIMIT:
                    print("Reached OMDb daily limit (10,000 calls). Saving checkpoint...")
                    df = pd.DataFrame(rows)
                    df.to_csv(output_csv, index=False)
                    return df

                omdb_row = get_omdb_details(tmdb_row["imdb_id"])
                omdb_calls_today += 1
                time.sleep(0.15)

                merged = {**tmdb_row, **omdb_row}
                rows.append(merged)
                existing_ids.add(tv_id)

                if len(rows) % 100 == 0:
                    pd.DataFrame(rows).to_csv(output_csv, index=False)
                    print(f" [CHECKPOINT] Auto-saved at {len(rows)} total shows.")

            page += 1
            
    print("\n[FINISHED] Scraping complete for all requested years!")
    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    return df


# Columns ordered by importance for renewal/cancellation prediction
ORDERED_COLUMNS = [
    "status",
    "target_renewed",
    "primary_network",
    "channel_type",
    "imdb_votes",
    "popularity_votes",
    "popularity_score",
    "imdb_rating",
    "audience_score",
    "metascore",
    "rotten_tomatoes_score",
    "tomato_meter",
    "tomato_user_meter",
    "lead_actors",
    "omdb_actors",
    "creators",
    "omdb_writer",
    "omdb_director",
    "genre",
    "omdb_genre",
    "format",
    "num_seasons",
    "omdb_total_seasons",
    "num_episodes",
    "season_length",
    "premiere_year",
    "premiere_month",
    "original_vs_adaptation",
    "ip_spin_off_reboot_story",
    "omdb_runtime",
    "omdb_rated",
    "omdb_awards",
    "omdb_plot",
    "title",
    "imdb_id",
    "tmdb_id",
    "tomato_consensus",
] 

if __name__ == "__main__":
    df_linked = build_linked_dataset(start_year=2010, end_year=2017)
    if not df_linked.empty:
        cols = [c for c in ORDERED_COLUMNS if c in df_linked.columns] + [
            c for c in df_linked.columns if c not in ORDERED_COLUMNS
        ]
        df_linked = df_linked[cols]
        df_linked.to_csv("tmdb_omdb_tv_renewal_final.csv", index=False)
        print(f"Saved {len(df_linked)} linked TV series.")