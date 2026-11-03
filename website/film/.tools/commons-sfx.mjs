// Search Wikimedia Commons for reusable sound recordings and list candidates with licence and duration.
// usage: node commons-sfx.mjs "<query>" [limit]
const [q, limit = 12] = process.argv.slice(2);
const UA = { 'User-Agent': 'InterstellarFilm/1.0 (hackathon film; contact via github tohraan)' };
const api = 'https://commons.wikimedia.org/w/api.php';
const params = new URLSearchParams({
  action: 'query', format: 'json', generator: 'search', gsrnamespace: '6', gsrlimit: String(limit),
  gsrsearch: `${q} filetype:audio`, prop: 'imageinfo', iiprop: 'url|extmetadata|mediatype|size',
});
const res = await fetch(`${api}?${params}`, { headers: UA });
const pages = Object.values((await res.json()).query?.pages ?? {});
const ok = /^(cc0|public domain|pd|cc by( \d\.\d)?|cc by-sa( \d\.\d)?)/i;
for (const p of pages.sort((a, b) => a.index - b.index)) {
  const ii = p.imageinfo?.[0];
  if (!ii) continue;
  const m = ii.extmetadata ?? {};
  const lic = m.LicenseShortName?.value ?? '?';
  const len = m.Length?.value ?? ii.duration ?? '';
  const desc = (m.ImageDescription?.value ?? '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').slice(0, 90);
  const artist = (m.Artist?.value ?? '').replace(/<[^>]+>/g, '').trim().slice(0, 40);
  console.log([ok.test(lic) ? 'OK ' : 'NO ', lic, `${Math.round(ii.size / 1024)}KB`, p.title, artist, desc, ii.url].join(' | '));
}
