# Judging rubric import

Use this command to bootstrap new scoring rubrics from a spreadsheet or pandas DataFrame export.

## Expected JSON shape

Save your rubric in a JSON file with the following structure:

```json
{
  "sections": [
    {
      "id": "innovation",
      "title": "Innovation",
      "weight": 0.25,
      "criteria": [
        {"id": "originality", "label": "Originality of the solution", "max_score": 6},
        {"id": "multidisciplinary", "label": "Intersection of disciplines", "max_score": 6}
      ]
    }
  ]
}
```

Each section must include a unique `id`, a human-friendly `title`, a `weight` between 0 and 1, and a list of `criteria`. Every criterion needs a unique `id`, a `label`, and a positive `max_score`. The sum of all section weights must equal 1.0.

### Converting from pandas

If you already have a scoring table in pandas, convert it with something like:

```python
(
    df
    .assign(weight=df["weight"].astype(float))
    .groupby(["section_id", "section_title", "weight"], as_index=False)
    .apply(lambda g: {
        "id": g.name[0],
        "title": g.name[1],
        "weight": g.name[2],
        "criteria": [
            {"id": row.criterion_id, "label": row.criterion_label, "max_score": float(row.max_score)}
            for row in g.itertuples()
        ],
    })
    .tolist()
)
```

Write the resulting dictionary to `rubric.json` with `json.dump`.

## Importing the rubric

Run the management command:

```bash
./env/bin/python manage.py import_rubric <edition_id> path/to/rubric.json --name "Fall 2025" --activate
```

- The command automatically increments the version number unless you provide `--rubric-version`.
- `--activate` deactivates the previous rubric for the edition so judges immediately see the new one.

After import, visit `/admin/judging/judgingrubric/` to review or tweak the definition.

## Launching the scoring portal

The Judges Guide page (`/event/judges`) renders a **Launch judging portal** button that links to the value of `JUDGING_PORTAL_URL`. By default this equals `/judging/`, sending judges to the internal dashboard created earlier. If your scoring tool lives on a different host or path, override `JUDGING_PORTAL_URL` in your settings or environment so the guide points to the correct destination.

## Evaluating teams via QR scans

Judges never have to create `JudgingProject` entries manually. Instead, each participant’s QR code doubles as the fast entry point to the team’s scoring page:

1. Share the `/judging/scan/<qr-code>/` URL pattern with your on-site scanners. The `<qr-code>` slug is the same value already embedded in the participant badges exported from the Friends app.
2. When a judge scans a badge, the redirect view resolves the participant’s team (`FriendsCode`), creates the corresponding `JudgingProject` for the current edition if it does not exist yet, refreshes the metadata (members, Devpost URL, track), and finally sends the judge to `/judging/project/<pk>/score/`.
3. The newly created project immediately appears on the dashboard for every judge, keeping the roster synchronized as teams move around.

If a participant scans with an unassigned QR (no FriendsCode), the judge receives a friendly error message instead of a 404. Fix the team membership in the Friends admin and retry the scan—no extra judging admin steps required.
