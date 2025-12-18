const API_BASE_URL = "http://localhost:8000";

const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const resultsDiv = document.getElementById("results");
const resultsInfo = document.getElementById("resultsInfo");
const loadingDiv = document.getElementById("loading");
const errorBox = document.getElementById("errorBox");
const randomButton = document.getElementById("randomButton");
const refineToggleBtn = document.getElementById("refineToggleBtn");
const refinePanel = document.getElementById("refinePanel");

// Toggle refine panel open/close
if (refineToggleBtn && refinePanel) {
  refineToggleBtn.addEventListener("click", (e) => {
    const isOpen = refineToggleBtn.getAttribute("aria-expanded") === "true";
    const newState = !isOpen;
    refineToggleBtn.setAttribute("aria-expanded", String(newState));
    refinePanel.setAttribute("aria-hidden", String(!newState));
    refinePanel.style.display = newState ? "block" : "none";
    // update triangle: up when open, down when closed
    refineToggleBtn.textContent = newState ? "▴" : "▾";
  });

  // close on Escape
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      refineToggleBtn.setAttribute("aria-expanded", "false");
      refinePanel.setAttribute("aria-hidden", "true");
      refinePanel.style.display = "none";
      refineToggleBtn.textContent = "▾";
    }
  });

  // close when clicking outside
  document.addEventListener("click", (ev) => {
    const target = ev.target;
    if (!refinePanel.contains(target) && !refineToggleBtn.contains(target) && refinePanel.style.display === "block") {
      refineToggleBtn.setAttribute("aria-expanded", "false");
      refinePanel.setAttribute("aria-hidden", "true");
      refinePanel.style.display = "none";
      refineToggleBtn.textContent = "▾";
    }
  });
}

searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;

  await searchComics(query);
});

randomButton.addEventListener("click", async () => {
  await fetchRandomComic();
});

function resetSearch() {
  resultsDiv.innerHTML = "";
  resultsInfo.textContent = "";
  errorBox.style.display = "none";
  loadingDiv.style.display = "block";
}

function showError(err) {
  loadingDiv.style.display = "none";
  errorBox.textContent = `Fehler: ${err.message}`;
  errorBox.style.display = "block";
  console.error("Search error:", err);
}

async function searchComics(query) {
  resetSearch();
  try {
    const response = await fetch(
      `${API_BASE_URL}/comics/search?q=${encodeURIComponent(query)}`
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    loadingDiv.style.display = "none";

    if (data.count === 0) {
      resultsInfo.textContent = `Keine Ergebnisse für "${query}"`;
      return;
    }

    resultsInfo.textContent = `${data.count} Ergebnis${
      data.count !== 1 ? "se" : ""
    } für "${query}"`;
    displayResults(data.comics);
  } catch (err) {
    showError(err);
  }
}

async function fetchRandomComic() {
  resetSearch();
  try {
    const response = await fetch(`${API_BASE_URL}/comics/random`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const comic = await response.json();
    loadingDiv.style.display = "none";
    resultsInfo.textContent = `Zufälliger Comic #${comic.num}: ${comic.title}`;
    displayResults([comic]);
  } catch (err) {
    showError(err);
  }
}

function displayResults(comics) {
  comics.forEach((comic) => {
    const card = document.createElement("div");
    card.className = "comic-card";

    const date = `${comic.day}.${comic.month}.${comic.year}`;

    card.innerHTML = `
                    <div class="comic-header">
                        <div>
                            <h2 class="comic-title">${escapeHtml(
                              comic.title
                            )}</h2>
                            <div class="comic-date">${date}</div>
                        </div>
                        <div class="comic-num">#${comic.num}</div>
                    </div>

                    <div class="comic-image">
                        <img src="${comic.img}" alt="${escapeHtml(
      comic.alt
    )}" loading="lazy">
                    </div>

                    <div class="comic-alt">
                        <strong>Alt-Text:</strong> ${escapeHtml(comic.alt)}
                    </div>

                    ${
                      comic.transcript
                        ? `
                        <div class="comic-transcript">
                            <strong>Transcript:</strong><br>
                            ${escapeHtml(comic.transcript)}
                        </div>
                    `
                        : ""
                    }
                `;

    resultsDiv.appendChild(card);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
