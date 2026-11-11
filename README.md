# Card Scanner

An iPhone home-screen app that scans Pokémon and One Piece cards and builds a list with:

- **TCGplayer link** (opens with the Near Mint filter)
- **Market price**: TCGplayer's market price, refreshed daily. Tap a printing (Holofoil, Reverse Holofoil, 1st Edition…) to switch prices.
- **Set it was released in**, plus the release month
- **PSA 9 and PSA 10 population**, once you link the card (see step 7)
- A running **total value** and a **CSV export**

Not included yet: lowest listing from well-rated sellers, and the last NM sale. To see those, use the TCGplayer button on any card.

It costs nothing to host. The only paid piece is the Claude AI API, which reads each photo. It's pay-as-you-go, one small request per photo.

---

## One-time setup (about 20 minutes)

### 1. Make a GitHub account
Sign up at **github.com**. The free plan is all you need.

### 2. Create the repository
1. Click **+** (top right) → **New repository**.
2. Name it `card-scanner`.
3. Choose **Public**. Free GitHub Pages hosting requires a public repository. Your keys never go into it; they stay on your phone.
4. Click **Create repository**.

### 3. Upload the files
1. Unzip `card-scanner.zip` on your computer.
2. On the new repository's page, click **uploading an existing file**.
3. Open the unzipped `card-scanner` folder, select **everything inside it**, and drag it onto the page. Include the `.github` folder; it's the part that refreshes prices every day.
   - **Mac:** `.github` is hidden in Finder. Press **Cmd + Shift + .** (period) to show it before dragging.
4. Click **Commit changes**.

**Check:** open the **Actions** tab. You should see a workflow named **"Update prices and publish app"**. If it's missing, the `.github` folder didn't upload. To fix that:
- Click **Add file → Create new file**.
- Name it `.github/workflows/update.yml`.
- Paste in everything from `setup/update.yml`.
- Commit.

The first run may fail with a red ✗. That's expected until the next step is done.

### 4. Turn on GitHub Pages
1. Go to **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

### 5. (Optional now) Add your PSA token
You only need this for PSA 9/10 counts.
1. Sign in at **psacard.com/publicapi** and copy your API token. The free plan allows about 100 lookups a day.
2. In your repository, go to **Settings → Secrets and variables → Actions → New repository secret**.
3. Name it `PSA_TOKEN`, paste the token, and save.

### 6. Build the app for the first time
1. Go to **Actions → Update prices and publish app → Run workflow → Run workflow**.
2. The first run downloads every Pokémon and One Piece card and takes about 5–10 minutes.
3. When it shows a green ✓, your app is live at:

   **`https://YOUR-GITHUB-USERNAME.github.io/card-scanner/`**

After that, the app updates itself every day at about 1:40 pm Pacific.

### 7. Install it on your iPhone
1. Open the link from step 6 in **Safari**. It has to be Safari.
2. Tap **Share** (the square with the arrow) → **Add to Home Screen** → **Add**.
3. Open **Card Scanner** from your home screen and tap the **gear** icon.
4. **Claude AI API key:**
   - Create one at **console.anthropic.com → API Keys**. You'll need to add a little credit under Billing.
   - Paste it into the app and tap **Save**.

You're ready to scan.

### 8. (Optional) Enable PSA linking from your phone
The app saves PSA links to your repository, so it needs a GitHub token that can only edit that one repository:
1. On GitHub, go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Give it any name and set expiration to the longest option.
3. **Repository access:** Only select repositories → `card-scanner`.
4. **Permissions → Repository permissions → Contents:** Read and write.
5. Generate it and copy it.
6. In the app's Settings, paste it into **GitHub token**. The repository is filled in for you. Tap **Save**.

---

## Using the app

- **Scan card** opens the camera. Lay the card flat in good light so the name and the number at the bottom are readable.
- **Photos** lets you pick several photos at once. A single photo can also hold several cards.
- A **yellow border** means the app isn't sure which version you have. This happens often with One Piece parallels, manga art, and alt arts. Tap **Change** and pick the right one.
- **Search** adds a card by name, number, or set without a photo.
- **Link PSA 9/10 pop:**
  - PSA's free API can't search by card name, so each card is linked once using the cert number of *any* PSA-graded copy of that exact card. The "Find a graded copy on eBay" button helps: the cert number is on the slab label in the photos.
  - Counts show up about 3 minutes later and refresh weekly after that.
- **Gear → Export list (CSV)** shares your list as a spreadsheet file.

## Good to know

- **Prices are up to a day old.** They come from TCGCSV, a free daily copy of TCGplayer's prices.
- **The market price isn't condition-specific.** It's TCGplayer's overall market price per printing, not a Near Mint-only number. For most cards it's close to Near Mint.
- **GitHub pauses daily runs after 60 days of no activity in the repository.** Linking a PSA card counts as activity. If prices stop updating, open the **Actions** tab and click **Enable workflow**.
- **Card reading uses Sonnet by default.** If it misreads cards often, switch the model to Opus in Settings. To save money, try Haiku.

## What's in here

| Path | What it does |
|---|---|
| `app/` | The iPhone app (HTML/CSS/JS, works offline once installed) |
| `scripts/build_prices.py` | Daily download of card and price data from TCGCSV |
| `scripts/build_psa.py` | Looks up PSA 9/10 population for linked cards |
| `psa-links.json` | Your PSA links (the app edits this for you) |
| `.github/workflows/update.yml` | Runs the two scripts daily and publishes the app |
| `tests/` | Automated tests (`node tests/test_matcher.js`, `python3 tests/test_build.py`) |
