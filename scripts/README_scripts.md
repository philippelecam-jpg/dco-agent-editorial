# scripts/

Outils de diagnostic et de recette pour dco-agent-editorial. Rien ici ne
tourne en production (ni cron, ni workflow) — ce sont des scripts lancés à
la main, ponctuellement.

## test_escalade_notification.py

Vérifie que l'escalade vers une revue humaine du pipeline week-end
(`agent_weekend_agentique.py`, fonction `_escalader_revue_humaine`)
déclenche bien un e-mail réel — création d'une issue GitHub, assignation,
notification — avant de laisser le dispositif tourner sans supervision.

```bash
export GITHUB_TOKEN=ghp_votre_jeton_personnel
python3 scripts/test_escalade_notification.py \
  --repo philippelecam-jpg/dco-agent-editorial \
  --assignee philippelecam-jpg \
  --cleanup
```

`--cleanup` ferme l'issue de test automatiquement une fois la vérification
faite. Sans assignation confirmée dans la sortie du script, vérifier les
réglages de notification du compte GitHub concerné
(`github.com/settings/notifications` → « Participating, @mentions and
custom » → Email) avant de chercher un problème côté code.

Ce script est générique : il ne dépend d'aucun fichier de ce repo, et peut
être réutilisé tel quel sur un dépôt client lors de la mise en place d'un
dispositif d'escalade similaire. Il fait partie d'un kit plus large
(modèle vierge + guide de questions d'annexe de gouvernance IA), centralisé
séparément — cf. Philippe pour l'emplacement à jour de ce kit.
