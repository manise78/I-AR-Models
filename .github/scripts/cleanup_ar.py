name: Pulizia modelli AR - 30 giorni

on:
  schedule:
    - cron: '23 3 * * *'
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Simulazione: elenca i modelli scaduti senza eliminarli'
        type: boolean
        required: true
        default: true

permissions:
  contents: read

concurrency:
  group: ar-cleanup
  cancel-in-progress: false

jobs:
  cleanup:
    if: github.repository == 'manise78/I-AR-Models' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Leggi lo script dal repository
        uses: actions/checkout@v4
        with:
          persist-credentials: false
          sparse-checkout: .github/scripts
      - name: Controlla ed elimina i modelli scaduti
        env:
          AR_CLEANUP_TOKEN: ${{ secrets.AR_CLEANUP_TOKEN }}
          AR_DRY_RUN: ${{ github.event_name == 'workflow_dispatch' && inputs.dry_run || false }}
        run: python3 .github/scripts/cleanup_ar.py
