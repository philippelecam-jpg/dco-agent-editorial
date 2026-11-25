# Ce que vous avez confié à un tiers sans le savoir

*Votre service IA externe fonctionne. Jusqu'au jour où il change ses conditions. Et là, vous découvrez ce que vous avez réellement externalisé.*

Un email arrive. Votre fournisseur de recherche documentaire IA modifie son modèle tarifaire avec trente jours de préavis. Vous ouvrez la console pour évaluer ce que vous pourriez exporter. Et vous réalisez que vous ne savez pas par où commencer.

Ce moment existe. Il arrive plus souvent qu'on ne le croit. Et il révèle une lacune qui n'est pas technique : c'est une lacune de connaissance sur ce que l'organisation a réellement confié à un tiers.

Ce que l'on confie sans le formaliser

Quand une PME ou une ETI intègre un service IA en production, elle connecte rarement un outil vierge. Elle l'adapte. Elle configure des filtres, des catégories, des paramètres sectoriels. Elle l'alimente avec des historiques de requêtes, des documents de référence, des règles métier. Elle construit, semaine après semaine, une couche de calibrage qui n'appartient ni au fournisseur ni vraiment à elle, parce qu'elle n'a jamais été documentée.

Cette couche, c'est ce qui rend l'outil utile. Et c'est précisément ce qui disparaît en cas de rupture.

Les développeurs parlent de vendor lock-in pour désigner la dépendance technique à un fournisseur. Mais le verrou dont il s'agit ici est différent. Il n'est pas dans le code. Il est dans la connaissance encodée à l'intérieur d'un service que l'organisation ne contrôle pas.

Un cas hypothétique pour poser le problème

Imaginez une ETI de conseil qui utilise depuis dix-huit mois un service IA de recherche documentaire. Au fil du temps, les équipes ont construit des indexes thématiques par secteur d'activité, configuré des filtres fins pour exclure certaines sources, affiné les pondérations selon les types de documents. Ce travail n'a jamais fait l'objet d'une documentation formelle. Il s'est accumulé dans l'interface du fournisseur.

Lorsque ce fournisseur annonce une refonte tarifaire qui multiplie les coûts par trois, l'ETI veut migrer. Elle découvre alors deux problèmes. Premier problème : les indexes thématiques ne sont pas exportables dans un format réutilisable ailleurs. Second problème : personne dans l'organisation ne sait précisément quelles règles ont été configurées, ni pourquoi. La connaissance métier a été encodée dans un outil externe, sans jamais être ancrée dans l'organisation elle-même.

Ce scénario est hypothétique. La situation qu'il décrit, elle, est structurelle.

Quatre catégories à cartographier avant la crise

Face à chaque service IA externe utilisé en production, quatre catégories méritent une attention spécifique.

Les données de calibrage. Ce sont les documents, exemples, historiques et corpus qui ont servi à paramétrer le service. Ont-ils été versés dans la plateforme sans copie locale ? Sont-ils récupérables dans un format standard ?

Les règles métier encodées. Filtres, pondérations, catégories, exclusions : ces configurations représentent souvent des mois de travail implicite. Elles existent dans l'interface du fournisseur, rarement dans un document interne. Si la plateforme ferme, elles disparaissent.

Les connecteurs personnalisés. Quand un service IA est connecté à un CRM, un ERP ou une base documentaire via des intégrations sur mesure, ces connexions ont un coût de reconstruction non négligeable. Ce coût est rarement anticipé.

L'historique des interactions. Les requêtes passées, les corrections apportées, les résultats validés ou rejetés : cet historique est une matière précieuse pour reconstruire ou réorienter un service. Il est souvent inaccessible en dehors de la plateforme d'origine.

La question n'est pas de tout exporter en permanence. Elle est de savoir ce qui est exportable, ce qui devrait l'être, et ce qui ne peut qu'être reproduit à partir d'une documentation interne suffisante.

Une décision de gouvernance, pas un projet informatique

Cartographier ce que l'on a confié à un tiers est une décision de gouvernance. Elle précède tout projet de migration ou de continuité. Elle n'appartient pas à la DSI seule, parce que les règles métier encodées dans un outil IA ne sont pas des données informatiques. Ce sont des décisions d'organisation qui ont pris la forme de paramètres.

La question à poser dans chaque direction concernée est simple : si ce service devenait inaccessible demain matin, que faudrait-il être capable de reconstituer, et en combien de temps ?

Cette question n'a pas de bonne réponse universelle. Elle a une bonne réponse par organisation, par fonction, par niveau d'exposition. Une fonction de qualification de leads automatisée tolère peut-être une interruption de quarante-huit heures. Une synthèse contractuelle utilisée en négociation active, non.

Structurer la connaissance avant de la déléguer

Le principe reste constant : une organisation ne peut déléguer à un service externe que ce qu'elle est capable de décrire elle-même. Si la connaissance métier n'existe que dans la configuration d'un outil tiers, elle n'appartient pas à l'organisation. Elle lui est prêtée, aux conditions du fournisseur.

Codifier les règles métier, documenter les choix de calibrage, maintenir une trace lisible des configurations : ce travail semble accessoire quand tout fonctionne. Il devient critique quand quelque chose change.

La réversibilité ne s'improvise pas au moment où elle devient nécessaire. Elle se prépare au moment où l'on intègre un nouveau service.

Quelle est, pour chaque outil IA que votre organisation utilise aujourd'hui en production, la réponse concrète à cette question : que faudrait-il reconstruire, et sur quelle base, si l'accès disparaissait dans trente jours ?

Décisions & Co

#TransformationIA #GouvernanceIA #PME #Résilience #KnowledgeManagement
