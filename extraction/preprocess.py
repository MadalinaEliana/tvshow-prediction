import re
import numpy as np
import pandas as pd

RAW = "data/tmdb_omdb_tv_renewal_final.csv"
TVMAZE = "data/tvmaze_tv_dataset.csv"
OUT_FULL = "data/tv_renewal_clean.csv"
MAX_PREMIERE_YEAR = 2024

df = pd.read_csv(RAW, low_memory=False)

tv = pd.read_csv(TVMAZE, low_memory=False).drop_duplicates("imdb_id")
tv = tv[["imdb_id", "tvmaze_weight_popularity", "schedule_days", "schedule_time",
         "runtime", "country", "language", "primary_network", "channel_type"]]
tv = tv.rename(columns={"runtime": "tv_runtime", "primary_network": "tv_network",
                        "channel_type": "tv_channel_type"})
df = df.merge(tv, on="imdb_id", how="left")
n0 = len(df)

# target: got a 2nd season; drop unresolved (still airing, 1 season) and recent shows
df["renewed_s2"] = (df["num_seasons"] >= 2).astype(int)
df = df[~((df.status == "Returning Series") & (df.num_seasons <= 1))]
df = df[df.num_seasons >= 1]
df = df[df.premiere_year <= MAX_PREMIERE_YEAR]

# cleaning
df["imdb_votes"] = pd.to_numeric(df["imdb_votes"].astype(str).str.replace(",", ""), errors="coerce")
df["runtime_min"] = pd.to_numeric(df["omdb_runtime"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
df["runtime_min"] = df["runtime_min"].fillna(df["tv_runtime"])
df = df.drop(columns=["tv_runtime"])
for c in ["schedule_days", "schedule_time", "tv_network", "tv_channel_type", "country"]:
    df.loc[df[c] == "Unknown", c] = np.nan
df.loc[df.audience_score == 0, "audience_score"] = np.nan
df.loc[df.primary_network == "Unknown", "primary_network"] = np.nan
df.loc[df.channel_type == "Unknown", "channel_type"] = np.nan
for c in ["lead_actors", "creators"]:
    df.loc[df[c] == "Unknown", c] = np.nan

df["genres_all"] = df["genre"].fillna(df["omdb_genre"])

# feature engineering
df["n_lead_actors"] = df["lead_actors"].fillna("").apply(lambda s: len([x for x in s.split(",") if x.strip()]))
df["n_creators"] = df["creators"].fillna("").apply(lambda s: len([x for x in s.split(",") if x.strip()]))
df["n_genres"] = df["genres_all"].fillna("").apply(lambda s: len([x for x in s.split(",") if x.strip()]))
df["is_spinoff"] = df["ip_spin_off_reboot_story"].str.contains("Spin-off", na=False).astype(int)
df["is_reboot"] = df["ip_spin_off_reboot_story"].str.contains("Reboot", na=False).astype(int)
df["is_based_on_ip"] = df["ip_spin_off_reboot_story"].str.contains("Known Story", na=False).astype(int)
df["is_adaptation"] = (df["original_vs_adaptation"] == "Adaptation / IP").astype(int)
df["plot_len_words"] = df["omdb_plot"].fillna("").str.split().str.len()
df["premiere_season"] = df["premiere_month"].map(
    {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
     6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"})
df["format_style"] = df["format"].str.extract(r"^(\w+)")[0]
df["format_structure"] = df["format"].str.extract(r"\((.*)\)")[0]
top_genres = ["Drama", "Comedy", "Crime", "Reality", "Animation", "Action & Adventure",
              "Sci-Fi & Fantasy", "Mystery", "Family", "Kids", "Documentary"]
for g in top_genres:
    df["g_" + re.sub(r"\W+", "_", g)] = df["genres_all"].fillna("").str.contains(g, regex=False).astype(int)

# drop leaky, empty and redundant columns
drop = ["status", "target_renewed", "num_seasons", "num_episodes", "season_length",
        "omdb_total_seasons", "omdb_awards", "metascore", "rotten_tomatoes_score",
        "tomato_meter", "tomato_user_meter", "tomato_consensus", "omdb_director",
        "omdb_writer", "omdb_runtime", "omdb_actors", "omdb_genre", "genre", "format",
        "ip_spin_off_reboot_story", "original_vs_adaptation"]
df = df.drop(columns=drop)

df = df.rename(columns={"renewed_s2": "target_renewed"})
df.to_csv(OUT_FULL, index=False)

print(f"raw rows: {n0} -> clean rows: {len(df)}")
print("target balance:\n", df.target_renewed.value_counts(normalize=True).round(3))
print("columns:", len(df.columns))
print(df.isna().mean().round(2).sort_values(ascending=False).head(12))