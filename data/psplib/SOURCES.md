# PSPLIB: источник и контрольные суммы

Скачано 2026-10-21 с https://www.om-db.wi.tum.de/psplib/getdata.php?mode=sm
(Kolisch, Sprecher 1997). Файлы в git не хранятся, см. `.gitignore`.

| Локальный путь | URL (относительно `https://www.om-db.wi.tum.de/psplib/`) | SHA-256 |
|---|---|---|
| `archives/j30.sm.zip` | `download_dataset.php?set=j30&mode=sm&format=zip` | `acd65524b95108a7ba08c1e512ffc6d028e9ba86a2a898b4462f71953e0f8467` |
| `archives/j60.sm.zip` | `download_dataset.php?set=j60&mode=sm&format=zip` | `bdb4e04c7ea3991d95180dda9d8cb2d5498a5770f5b546515d65c9a932594eab` |
| `archives/j120.sm.zip` | `download_dataset.php?set=j120&mode=sm&format=zip` | `52a42df7146a0a409ede597be8b864d8748a4578a3d94bd477469172a5477b3b` |
| `solutions/j30_opt.txt` | `download_solution.php?set=j30&mode=sm&type=opt` | `9036456d909d5d2102975c13dd6fe36fe503b3ed1df5b91fa652aa7dc9648ee3` |
| `solutions/j30_hrs.txt` | `download_solution.php?set=j30&mode=sm&type=hrs` | `66211bd393e29867fb4bf26f7762b4c5e37c68adfcbe7a51c9ae21841f9308a6` |
| `solutions/j60_hrs.txt` | `download_solution.php?set=j60&mode=sm&type=hrs` | `7eef616a8d05d1e12b363d48b47ba0fcac0528a79569aadff3b638a44982e8b7` |
| `solutions/j60_lb.txt` | `download_solution.php?set=j60&mode=sm&type=lb` | `a4107cb3cfc23ecc7880ab2324b94b060e28721f4d62b12f3de44b05c292c528` |
| `solutions/j120_hrs.txt` | `download_solution.php?set=j120&mode=sm&type=hrs` | `60996c50333ed2f4716f9fb511cc05176bb1be1b514e47863c173f690fcaf407` |
| `solutions/j120_lb.txt` | `download_solution.php?set=j120&mode=sm&type=lb` | `5adea8a0578349a3e104165794fcb4154408e85937a70605b592bc8e5f7b8662` |

`instances/<set>/` — распакованные архивы: J30 и J60 по 480 файлов, J120 — 600.
`instances/j30/j301_1.sm` совпадает с `data/raw/1_j301_1.txt` (Case 1).

Типы решений: `opt` — доказанные оптимумы (только J30), `hrs` — лучшие известные
решения (эвристики), `lb` — нижние границы.
