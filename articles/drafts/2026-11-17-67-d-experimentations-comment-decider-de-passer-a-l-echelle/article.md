# 67 % d'expérimentations : comment décider de passer à l'échelle

*La majorité des automatismes IA restent en pilote. Non par manque d'ambition, mais par absence de critères pour trancher.*

La Banque de France l'a mesuré début 2026 : 67 % des entreprises d'au moins 20 salariés déclarant un usage d'IA générative qualifient cet usage de « principalement limité ou expérimental ». Ce chiffre ne témoigne pas d'un manque de volonté. Il témoigne d'un manque de méthode pour franchir la ligne.

Un pilote reste un pilote tant que personne n'a défini ce qui autoriserait à en sortir.

Le piège du pilote permanent

Déployer un automatisme sur un périmètre restreint est une démarche saine. Laisser ce périmètre restreint devenir la norme par confort ou par défaut, c'est une dérive. L'organisation s'habitue à l'outil. Les équipes contournent les cas difficiles. Le pilote tourne, personne ne le challenge. Et deux ans plus tard, l'entreprise présente le même automatisme comme une « initiative en cours ».

Le passage à l'échelle n'est pas une étape technique. C'est une décision de gouvernance. Elle réclame des critères, une instance, et un moment précis pour trancher.

Trois dimensions pour construire un seuil

Prenons un cas hypothétique : une ETI de distribution souhaitant automatiser le traitement de ses bons de commande fournisseurs. L'automatisme lit les documents entrants, extrait les lignes, les importe dans l'ERP. Sur le pilote, il couvre 60 % des flux. Les 40 % restants sont traités manuellement.

Pour décider de généraliser, trois dimensions doivent être évaluées conjointement.

Première dimension : le taux d'erreur brut. Combien de bons de commande l'automatisme traite-t-il sans intervention humaine et sans erreur détectée ? Dans notre exemple hypothétique, si ce taux atteint 94 %, la question n'est plus de savoir si la machine est fiable. Elle est de savoir si les 6 % restants représentent un risque acceptable, et pour qui.

Deuxième dimension : la nature et la fréquence des exceptions. Toutes les exceptions ne se valent pas. Un bon de commande mal formaté par un fournisseur ponctuel n'a pas le même poids qu'une ligne de commande portant sur un article stratégique ou soumis à des contraintes réglementaires. Il faut cartographier les exceptions : sont-elles prévisibles, récurrentes, traitables par règle, ou intrinsèquement imprévisibles ? Un automatisme qui génère 50 exceptions par mois sur des cas bien balisés est plus mûr pour la généralisation qu'un automatisme qui en génère 10 sur des cas inattendus chaque fois différents.

Troisième dimension : la satisfaction des utilisateurs métier. C'est la plus souvent négligée. Les équipes qui travaillent quotidiennement avec l'automatisme savent ce qu'il rate, ce qu'il déforme, ce qu'il force à corriger en silence. Un taux d'erreur formellement bas peut masquer une charge de vérification élevée que personne ne mesure. Le seuil de qualité acceptable ne se lit pas uniquement dans les logs. Il se lit dans le temps que les équipes passent à corriger ce que l'automatisme ne dit pas avoir mal fait.

Qui fixe le seuil, et comment

C'est la question que la plupart des organisations évitent. Fixer un seuil, c'est prendre une responsabilité. Personne ne veut signer sous une décision qui pourrait se retourner.

Pourtant, la réponse est assez claire. Le seuil de qualité acceptable doit être co-construit entre trois parties : le responsable métier du processus concerné, qui connaît le coût réel d'une erreur dans son contexte, le responsable de la donnée ou de la gouvernance IA, qui s'assure que les critères sont mesurables et cohérents avec la politique globale, et la direction générale, qui valide que le niveau de risque résiduel est compatible avec les engagements de l'entreprise vis-à-vis de ses clients, partenaires ou régulateurs.

Dans une PME, ces trois rôles peuvent être portés par deux personnes. L'important n'est pas la structure, c'est la traçabilité de la décision. Quelqu'un doit pouvoir dire, dans six mois : voici le seuil que nous avions fixé, voici pourquoi, voici ce que nous avons mesuré.

Le processus de validation avant bascule

Une fois les seuils posés, le processus de validation doit être court et délibéré. Trois étapes suffisent.

D'abord, une revue des données du pilote sur une période représentative, incluant des périodes de charge haute et basse. Un automatisme de traitement de commandes qui performe bien en juillet peut révéler ses limites en novembre, lors des campagnes de réapprovisionnement.

Ensuite, une simulation du déploiement généralisé : que se passe-t-il si le volume traité triple ? Les exceptions vont-elles croître de façon linéaire ou exponentielle ? Les équipes qui gèrent les cas manuels ont-elles la capacité d'absorber ce volume sans dégrader la qualité de leur propre travail ?

Enfin, une décision formalisée, même courte. Un document qui acte les seuils retenus, les limites connues, et les conditions de réversibilité si les mesures post-déploiement s'écartent des prévisions. Ce n'est pas de la bureaucratie. C'est ce qui permet de piloter au lieu de subir.

Ce que révèle la décision de bascule

La décision de généraliser un automatisme est un révélateur organisationnel. Elle montre si l'entreprise sait mesurer ce qu'elle déploie, si les responsables métier ont voix au chapitre sur les outils qui transforment leur travail, et si la direction générale traite l'IA comme un investissement gouverné ou comme une boîte noire que l'on surveille du coin de l'oeil.

Bpifrance le mesure : dans 73 % des cas, les projets IA sont impulsés par le dirigeant. C'est une force. Mais l'impulsion d'un dirigeant ne suffit pas à construire un seuil de qualité. Elle doit s'adosser à une méthode que les équipes peuvent appliquer sans lui, sur le prochain automatisme, puis sur celui d'après.

La vraie question n'est pas : cet automatisme est-il assez bon pour être généralisé ? Elle est : notre organisation est-elle assez structurée pour décider elle-même quand un automatisme est assez bon ?

Ces deux questions n'ont pas la même réponse. Et seule la seconde garantit que les 67 % d'expérimentations actuelles deviendront, à terme, autre chose que des expérimentations.

Décisions & Co

#TransformationIA #PME #ETI #GouvernanceIA #PassageÀLéchelle
