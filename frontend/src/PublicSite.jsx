import React from "react";

const products = [
  ["OneCore Business OS","Finance, sales, inventory and procurement connected in one operating workspace.","Business"],
  ["OneCore POS & Retail","Checkout, stock, payments and store operations designed for connected and offline work.","Commerce"],
  ["OneCore School OS","Admissions, academics, attendance, assessments and school finance.","Education"],
  ["OneCore Hospital OS","Patient administration and clinical operations with controlled access to sensitive records.","Healthcare"],
  ["OneCore Finance OS","SACCO, microfinance, chama, savings and credit workflows.","Finance"],
  ["OneCore HR & Payroll","People operations, attendance and Kenya-aware payroll workflows.","People"],
  ["OneCore AI, Cloud & Connect","Intelligence, secure files and integration capabilities across the ecosystem.","Platform"],
  ["OneCore Property, Hotel & Services","Purpose-built workflows for property, hospitality and service organizations.","Industry"],
];

const solutions = [
  ["Retail & distribution","Sales, point of sale, inventory, procurement and financial control."],
  ["Education","Learner records, academic operations, assessments and fee management."],
  ["Healthcare","Patient administration, hospital workflows, pharmacy and laboratory operations."],
  ["Finance & membership","Member administration, savings, loans, repayments and portfolio oversight."],
  ["Growing organizations","CRM, HR, payroll, projects, workflows and reporting in one workspace."],
];

function Brand({light=false}) {
  return <a className={light?"public-brand light":"public-brand"} href="/" aria-label="OneCore home"><span className="public-brand-mark">O</span><span><strong>onecore</strong><small>TECHNOLOGIES LTD</small></span></a>;
}
function Attribution(){return <a className="public-attribution" href="https://onecore.co.ke">Powered by OneCore Technologies Ltd</a>;}

export default function PublicSite(){
  return <div className="public-site">
    <header className="public-header"><div className="public-header-inner"><Brand/><nav aria-label="Main navigation"><a href="#products">Products</a><a href="#solutions">Solutions</a><a href="#about">About</a><a href="#trust">Trust</a></nav><div className="public-header-actions"><a className="public-signin" href="/login">Sign in</a><a className="public-cta" href="/login">Enter OneCore <span aria-hidden="true">↗</span></a></div></div></header>
    <main>
      <section className="public-hero"><div className="public-hero-inner"><div className="public-hero-copy"><span className="public-kicker">ENTERPRISE SOFTWARE FOR AFRICA</span><h1>One platform.<br/><em>Every organization.</em><br/>Anywhere.</h1><p>Bring your people, processes and information together with an intelligent ecosystem built for the way organizations work across Africa.</p><div className="public-hero-actions"><a className="public-cta large" href="#products">Explore the ecosystem <span aria-hidden="true">→</span></a><a className="public-outline" href="/login">Sign in to workspace</a></div><div className="public-proof"><span>01 / CONNECTED OPERATIONS</span><span>02 / INDUSTRY SOLUTIONS</span><span>03 / SHARED PLATFORM</span></div></div><div className="public-hero-visual" aria-label="Connected OneCore platform illustration"><div className="public-orbit orbit-one"/><div className="public-orbit orbit-two"/><div className="public-orbit orbit-three"/><div className="public-core-mark">O</div><span className="orbit-label label-a">BUSINESS OS</span><span className="orbit-label label-b">INDUSTRY OS</span><span className="orbit-label label-c">ONECORE AI</span></div></div><div className="public-hero-bottom"><span>POWERING AFRICA'S ORGANIZATIONS</span><span>THROUGH INTELLIGENT SOFTWARE</span></div></section>
      <section className="public-intro" id="about"><div><span className="public-kicker">THE ONECORE APPROACH</span><h2>Less fragmentation.<br/><span>More connected work.</span></h2></div><div><p>OneCore Technologies Ltd brings business systems, industry applications and shared digital services into one connected ecosystem.</p><p>Start with the capabilities your organization needs, then connect more workflows as your operations grow—while identity, permissions, configuration and governance remain consistent.</p></div></section>
      <section className="public-products" id="products"><div className="public-section-heading"><div><span className="public-kicker">THE ECOSYSTEM</span><h2>Purpose-built products.<br/><span>One connected foundation.</span></h2></div><p>Modular tools that work together across teams, locations and industries.</p></div><div className="public-product-grid">{products.map((p,i)=><article className="public-product-card" key={p[0]}><div className="public-product-top"><span>0{i+1}</span><span>{p[2]}</span></div><div className="public-product-symbol">{["◈","▣","▤","✚","◎","◷","⌘","⌂"][i]}</div><h3>{p[0]}</h3><p>{p[1]}</p><a href="/login" aria-label={"Explore "+p[0]+" in OneCore"}>Explore product <span aria-hidden="true">↗</span></a></article>)}</div></section>
      <section className="public-solutions" id="solutions"><div className="public-section-heading"><div><span className="public-kicker">BUILT AROUND YOUR WORK</span><h2>Solutions for the<br/><span>work that matters.</span></h2></div><p>Shared platform services support focused workflows for different kinds of organizations.</p></div><div className="public-solution-list">{solutions.map((s,i)=><article key={s[0]}><span>0{i+1}</span><div><h3>{s[0]}</h3><p>{s[1]}</p></div><a href="/login" aria-label={"Open "+s[0]+" solution"}>↗</a></article>)}</div></section>
      <section className="public-platform" id="trust"><div className="public-platform-copy"><span className="public-kicker">THE SHARED FOUNDATION</span><h2>Designed to connect.<br/><em>Built to govern.</em></h2><p>OneCore is designed around a modular platform with shared identity, tenant-aware permissions, auditability, integrations and operational controls.</p><a className="public-outline light-outline" href="/docs">Explore API documentation <span aria-hidden="true">↗</span></a></div><div className="public-pillar-grid"><div><b>01</b><strong>Core Platform</strong><span>Identity · Tenancy · Access</span></div><div><b>02</b><strong>Products</strong><span>Business · Industry · AI</span></div><div><b>03</b><strong>Digital Ecosystem</strong><span>Web · Docs · Developers</span></div><div><b>04</b><strong>Operations Centre</strong><span>Monitoring · Incidents · Releases</span></div><div><b>05</b><strong>Enterprise Governance</strong><span>Security · Privacy · Continuity</span></div></div></section>
      <section className="public-cta-band"><div><span className="public-kicker">ONE PLATFORM. MANY POSSIBILITIES.</span><h2>Bring your organization<br/>into one connected ecosystem.</h2></div><a className="public-cta large" href="/login">Access OneCore <span aria-hidden="true">↗</span></a></section>
    </main>
    <footer className="public-footer"><div className="public-footer-main"><div><Brand light/><p>Powering Africa's Organizations Through Intelligent Software.</p></div><div><strong>Explore</strong><a href="#products">Products</a><a href="#solutions">Solutions</a><a href="#about">About OneCore</a></div><div><strong>Platform</strong><a href="/login">Customer workspace</a><a href="/docs">API documentation</a><a href="/health">Service health</a></div><div><strong>Trust</strong><a href="#trust">Platform principles</a><a href="/docs">Developer resources</a></div></div><div className="public-footer-bottom"><span>© {new Date().getFullYear()} OneCore Technologies Ltd. All rights reserved.</span><Attribution/><span>One Platform. Every Organization. Anywhere.</span></div></footer>
  </div>;
}
