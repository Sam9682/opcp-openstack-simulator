#!/usr/bin/env python3
"""Generate a marketing-style PDF for OPCP OpenStack Simulator - SkillHub Labs."""
from weasyprint import HTML

html_content = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
@page {
    size: A4;
    margin: 0;
}
body {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 0;
    color: #2c3e50;
    line-height: 1.6;
}

/* Cover Page */
.cover {
    height: 297mm;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    color: white;
    padding: 60px;
    page-break-after: always;
}
.cover h1 {
    font-size: 42px;
    font-weight: 700;
    margin-bottom: 20px;
    letter-spacing: -0.5px;
}
.cover .subtitle {
    font-size: 22px;
    font-weight: 300;
    opacity: 0.9;
    margin-bottom: 40px;
}
.cover .tagline {
    font-size: 16px;
    font-weight: 300;
    opacity: 0.7;
    border-top: 1px solid rgba(255,255,255,0.3);
    padding-top: 30px;
    margin-top: 40px;
}
.cover .brand {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 60px;
    opacity: 0.8;
}

/* Content Pages */
.page {
    padding: 50px 60px;
    page-break-after: always;
}
.page:last-child {
    page-break-after: avoid;
}
h2 {
    font-size: 28px;
    color: #0f3460;
    font-weight: 700;
    margin-bottom: 25px;
    padding-bottom: 10px;
    border-bottom: 3px solid #e94560;
}
h3 {
    font-size: 20px;
    color: #16213e;
    font-weight: 600;
    margin-top: 30px;
    margin-bottom: 15px;
}
p {
    font-size: 14px;
    margin-bottom: 15px;
    color: #444;
}
.intro-text {
    font-size: 16px;
    color: #555;
    line-height: 1.8;
    margin-bottom: 30px;
}

/* Feature Cards */
.features {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    margin: 30px 0;
}
.feature-card {
    background: #f8f9fa;
    border-radius: 12px;
    padding: 25px;
    width: 45%;
    border-left: 4px solid #e94560;
}
.feature-card h4 {
    font-size: 16px;
    color: #0f3460;
    margin: 0 0 10px 0;
    font-weight: 600;
}
.feature-card p {
    font-size: 13px;
    color: #666;
    margin: 0;
}

/* Benefits List */
.benefits {
    list-style: none;
    padding: 0;
}
.benefits li {
    font-size: 15px;
    padding: 12px 0 12px 35px;
    position: relative;
    border-bottom: 1px solid #eee;
}
.benefits li::before {
    content: "\\2713";
    position: absolute;
    left: 0;
    color: #e94560;
    font-weight: 700;
    font-size: 18px;
}

/* Timeline */
.timeline {
    margin: 30px 0;
}
.timeline-item {
    display: flex;
    align-items: flex-start;
    margin-bottom: 20px;
}
.timeline-badge {
    background: #0f3460;
    color: white;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 14px;
    margin-right: 20px;
    flex-shrink: 0;
}
.timeline-content {
    flex: 1;
}
.timeline-content h4 {
    margin: 0 0 5px 0;
    font-size: 16px;
    color: #16213e;
}
.timeline-content p {
    margin: 0;
    font-size: 13px;
    color: #666;
}

/* Modules Grid */
.modules-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 15px;
    margin: 25px 0;
}
.module-card {
    background: linear-gradient(135deg, #f8f9fa, #e9ecef);
    border-radius: 10px;
    padding: 20px;
    width: 44%;
    text-align: center;
}
.module-card .module-number {
    background: #e94560;
    color: white;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 10px;
}
.module-card h4 {
    font-size: 15px;
    color: #0f3460;
    margin: 8px 0;
}
.module-card p {
    font-size: 12px;
    color: #666;
    margin: 0;
}

/* CTA Section */
.cta {
    background: linear-gradient(135deg, #0f3460, #16213e);
    border-radius: 15px;
    padding: 40px;
    text-align: center;
    color: white;
    margin-top: 40px;
}
.cta h3 {
    color: white;
    font-size: 24px;
    margin: 0 0 15px 0;
}
.cta p {
    color: rgba(255,255,255,0.8);
    font-size: 15px;
    margin-bottom: 25px;
}
.cta .contact {
    font-size: 18px;
    font-weight: 600;
    color: #e94560;
}

/* Highlight Box */
.highlight-box {
    background: linear-gradient(135deg, #fff3f5, #ffeef0);
    border: 1px solid #e94560;
    border-radius: 12px;
    padding: 25px;
    margin: 25px 0;
}
.highlight-box h4 {
    color: #e94560;
    margin: 0 0 10px 0;
    font-size: 16px;
}

/* Environment section */
.env-cards {
    display: flex;
    gap: 20px;
    margin: 25px 0;
}
.env-card {
    flex: 1;
    background: white;
    border: 2px solid #e9ecef;
    border-radius: 12px;
    padding: 25px;
    text-align: center;
}
.env-card h4 {
    color: #0f3460;
    font-size: 16px;
    margin: 0 0 15px 0;
}
.env-card ul {
    text-align: left;
    padding-left: 20px;
    font-size: 13px;
    color: #666;
}
.env-card ul li {
    margin-bottom: 8px;
}

/* Service table */
.service-table {
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 13px;
}
.service-table th {
    background: #0f3460;
    color: white;
    padding: 10px 15px;
    text-align: left;
}
.service-table td {
    padding: 10px 15px;
    border-bottom: 1px solid #eee;
}
.service-table tr:nth-child(even) {
    background: #f8f9fa;
}

/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    font-size: 11px;
    color: #999;
    margin-top: 40px;
}
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover">
    <h1>OPCP OpenStack<br>Simulator</h1>
    <div class="subtitle">Un environnement d'entraînement OpenStack<br>complet et sans risque avec les SkillHub Labs</div>
    <div class="tagline">
        Keystone &bull; Nova &bull; Neutron &bull; Cinder &bull; Ironic &bull; Glance<br>
        Simulateur in-memory, API REST compatible, CLI OpenStack standard
    </div>
    <div class="brand">PSMC OVHcloud</div>
</div>

<!-- PAGE 2: INTRODUCTION & VALUE PROPOSITION -->
<div class="page">
    <h2>Pratiquez OpenStack sans infrastructure</h2>
    <p class="intro-text">
        Le simulateur OpenStack OPCP est un environnement d'entraînement léger, entièrement
        en Python, qui reproduit fidèlement les API des services OpenStack principaux.
        Plus besoin d'un cluster complet : formez vos équipes sur un simple poste de travail
        avec des réponses réalistes (UUIDs, timestamps, codes d'erreur) et des quotas simulés.
    </p>

    <h3>Pourquoi un simulateur ?</h3>
    <ul class="benefits">
        <li>Zéro coût d'infrastructure — fonctionne sur n'importe quelle machine avec Python 3.9+</li>
        <li>Démarrage instantané — aucune attente pour le boot des services</li>
        <li>Comportement déterministe — pas de problèmes réseau ou de race conditions</li>
        <li>Réponses réalistes — UUIDs, timestamps, codes de statut identiques à OpenStack</li>
        <li>Quotas appliqués — simule les limites de ressources comme en production</li>
        <li>Compatibilité CLI complète — fonctionne avec python-openstackclient standard</li>
    </ul>

    <div class="highlight-box">
        <h4>Idéal pour la formation</h4>
        <p style="margin:0; font-size: 14px; color: #555;">
            Conçu pour le programme opcp-openstack-first-steps, le simulateur permet aux stagiaires
            de pratiquer toutes les opérations OpenStack dans un environnement sûr et reproductible.
            Déployable en Docker en une seule commande.
        </p>
    </div>
</div>

<!-- PAGE 3: SERVICES SIMULÉS -->
<div class="page">
    <h2>6 services OpenStack simulés</h2>
    <p class="intro-text">
        Le simulateur implémente les API REST complètes de 6 services OpenStack majeurs,
        permettant une formation progressive de l'authentification au déploiement multi-ressources.
    </p>

    <table class="service-table">
        <tr>
            <th>Service OpenStack</th>
            <th>Composant</th>
            <th>Fonctionnalités</th>
        </tr>
        <tr>
            <td>Keystone (Identity)</td>
            <td>AuthManager</td>
            <td>Tokens, application credentials, validation, expiration</td>
        </tr>
        <tr>
            <td>Nova (Compute)</td>
            <td>ComputeManager</td>
            <td>Instances, flavors, images, resize, snapshot, delete</td>
        </tr>
        <tr>
            <td>Neutron (Network)</td>
            <td>NetworkManager</td>
            <td>Networks, subnets, routeurs, ports, bonds LACP</td>
        </tr>
        <tr>
            <td>Cinder (Block Storage)</td>
            <td>VolumeManager</td>
            <td>Volumes, attach/detach, snapshots</td>
        </tr>
        <tr>
            <td>Ironic (Baremetal)</td>
            <td>BaremetalManager</td>
            <td>Nodes, ports, provision state machine, power control</td>
        </tr>
        <tr>
            <td>Glance (Image)</td>
            <td>ImageManager</td>
            <td>Listing et consultation d'images (stub)</td>
        </tr>
    </table>

    <h3>Architecture en couches</h3>
    <div class="env-cards">
        <div class="env-card">
            <h4>API REST (Flask)</h4>
            <ul>
                <li>Endpoints compatibles CLI</li>
                <li>Validation de tokens</li>
                <li>Catalogue de services</li>
                <li>Gestion d'erreurs HTTP</li>
            </ul>
        </div>
        <div class="env-card">
            <h4>Managers</h4>
            <ul>
                <li>Logique métier</li>
                <li>Contrôle des quotas</li>
                <li>Machine à états</li>
                <li>Détection de doublons</li>
            </ul>
        </div>
        <div class="env-card">
            <h4>Infrastructure</h4>
            <ul>
                <li>ResourceStore (mémoire)</li>
                <li>ResourceLimiter</li>
                <li>Modèles dataclass</li>
                <li>Exceptions spécialisées</li>
            </ul>
        </div>
    </div>
</div>

<!-- PAGE 4: PROGRAMME DE FORMATION -->
<div class="page">
    <h2>Un parcours progressif avec le simulateur</h2>

    <div class="timeline">
        <div class="timeline-item">
            <div class="timeline-badge">1</div>
            <div class="timeline-content">
                <h4>Installation et Configuration — ~30min</h4>
                <p>Clonage du dépôt, docker compose up, validation du endpoint /health, configuration de la CLI OpenStack.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">2</div>
            <div class="timeline-content">
                <h4>Authentification et Tokens — ~45min</h4>
                <p>Application credentials, émission de tokens, validation, expiration. Comprendre le flux d'authentification Keystone.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">3</div>
            <div class="timeline-content">
                <h4>Compute et Réseau — ~1h30</h4>
                <p>Création d'instances, gestion des flavors et images. Réseaux, subnets, routeurs et security groups.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">4</div>
            <div class="timeline-content">
                <h4>Volumes et Baremetal — ~1h</h4>
                <p>Stockage bloc, attachement aux instances, snapshots. Gestion de nœuds baremetal et machine à états de provisionnement.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">5</div>
            <div class="timeline-content">
                <h4>Orchestration et Déploiement complet — ~1h</h4>
                <p>Déploiement multi-ressources avec les scripts Python, gestion des quotas, bonnes pratiques, nettoyage.</p>
            </div>
        </div>
    </div>

    <div class="highlight-box">
        <h4>Déploiement simplifié</h4>
        <p style="margin:0; font-size: 14px; color: #555;">
            Le simulateur se lance en une seule commande : <code>docker compose up -d</code>.
            Interface web sur le port 8080, API sur le port 5000. Compatible HTTPS via nginx.
        </p>
    </div>
</div>

<!-- PAGE 5: MODULES DÉTAILLÉS -->
<div class="page">
    <h2>Fonctionnalités clés du simulateur</h2>
    <p class="intro-text">
        Chaque fonctionnalité reproduit fidèlement le comportement d'un vrai cluster OpenStack,
        permettant une transition transparente vers un environnement de production.
    </p>

    <div class="modules-grid">
        <div class="module-card">
            <div class="module-number">1</div>
            <h4>Authentification</h4>
            <p>Password, app credentials, tokens avec expiration</p>
        </div>
        <div class="module-card">
            <div class="module-number">2</div>
            <h4>Compute</h4>
            <p>Create, resize, snapshot, delete, list instances</p>
        </div>
        <div class="module-card">
            <div class="module-number">3</div>
            <h4>Réseau</h4>
            <p>Networks, subnets, routeurs, ports, bonds LACP</p>
        </div>
        <div class="module-card">
            <div class="module-number">4</div>
            <h4>Stockage</h4>
            <p>Volumes, attach/detach, snapshots bloc</p>
        </div>
        <div class="module-card">
            <div class="module-number">5</div>
            <h4>Sécurité</h4>
            <p>Security groups, règles ingress/egress, CIDR</p>
        </div>
        <div class="module-card">
            <div class="module-number">6</div>
            <h4>Baremetal</h4>
            <p>Nodes, provision state machine, power control</p>
        </div>
        <div class="module-card">
            <div class="module-number">7</div>
            <h4>Quotas</h4>
            <p>Limites configurables via conf/limits.ini</p>
        </div>
        <div class="module-card">
            <div class="module-number">8</div>
            <h4>Erreurs réalistes</h4>
            <p>401, 404, 409, 413 — identiques à OpenStack</p>
        </div>
    </div>

    <h3>À qui s'adresse ce simulateur ?</h3>
    <div class="features">
        <div class="feature-card">
            <h4>Stagiaires en formation</h4>
            <p>Étudiants du programme opcp-openstack-first-steps qui découvrent les API OpenStack.</p>
        </div>
        <div class="feature-card">
            <h4>Formateurs et Instructeurs</h4>
            <p>Besoin d'un environnement portable pour des démos sans infrastructure lourde.</p>
        </div>
        <div class="feature-card">
            <h4>Développeurs Cloud</h4>
            <p>Construction d'outils interagissant avec les API OpenStack, besoin d'un backend de test rapide.</p>
        </div>
        <div class="feature-card">
            <h4>Équipes DevOps</h4>
            <p>Tests d'intégration et validation de scripts d'automatisation sans cluster réel.</p>
        </div>
    </div>
</div>

<!-- PAGE 6: RESULTS & CTA -->
<div class="page">
    <h2>Vos acquis avec le simulateur</h2>
    <ul class="benefits">
        <li>Maîtrise de la CLI OpenStack standard (python-openstackclient)</li>
        <li>Compréhension des flux d'authentification Keystone</li>
        <li>Capacité à gérer le cycle de vie complet des instances</li>
        <li>Maîtrise du réseau : networks, subnets, routeurs, security groups</li>
        <li>Gestion du stockage bloc et des snapshots</li>
        <li>Compréhension de la machine à états baremetal (Ironic)</li>
        <li>Utilisation du SDK Python openstack_simulator</li>
        <li>Déploiement Docker avec HTTPS et reverse proxy nginx</li>
    </ul>

    <div class="highlight-box">
        <h4>Prérequis simples</h4>
        <p style="margin:0; font-size: 14px; color: #555;">
            Python 3.9+, Docker et Docker Compose (optionnel). Le simulateur fournit tout le reste :
            code, API, documentation web intégrée, et scripts de test.
        </p>
    </div>

    <div class="cta">
        <h3>Prêt à former vos équipes ?</h3>
        <p>Contactez notre équipe pour planifier votre session SkillHub Labs avec le simulateur OpenStack.</p>
        <div class="contact">psmc@ovhcloud.com</div>
    </div>

    <div class="footer">
        <p>&copy; PSMC OVHcloud - Programme OPCP OpenStack Simulator - SkillHub Labs</p>
    </div>
</div>

</body>
</html>"""

output_path = "/home/slepetre/workspace/forgejo/opcp-openstack-simulator/docs/OPCP-OpenStack-Simulator.pdf"
HTML(string=html_content).write_pdf(output_path)
print(f"PDF generated: {output_path}")
