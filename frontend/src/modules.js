export const groups = [
 {title:"Workspace",items:[
  ["Overview","/","▦","Your organization at a glance","Dashboard"],
  ["Organizations","/organizations","⌂","Organizations, memberships and branches","Platform"],
 ]},
 {title:"Business operations",items:[
  ["Accounting","/accounting","▤","General ledger, journals, invoices, budgets and close","Finance"],
  ["Point of sale","/pos","▣","Checkout, shifts, returns and reconciliation","Commerce"],
  ["Inventory","/inventory","▧","Products, stock movements and reservations","Operations"],
  ["Procurement","/procurement","⇄","Requisitions, suppliers, purchase orders and approvals","Operations"],
  ["CRM & Sales","/crm","◎","Contacts, leads, quotes and customer activity","Growth"],
  ["Campaign automation","/crm/automation","✳","Campaigns, audiences and delivery workflows","Growth"],
  ["Sales forecasting","/crm/forecast","⌁","Pipeline forecasts and sales performance","Growth"],
 ]},
 {title:"Industry solutions",items:[
  ["School management","/school","▣","Learners, classes, attendance and assessments","Education"],
  ["Advanced school","/school/advanced","▥","Advanced school administration workflows","Education"],
  ["Hospital","/healthcare/hospital","✚","Hospital operations and clinical workflows","Healthcare"],
  ["Healthcare","/healthcare","♡","Patient privacy, access and consent controls","Healthcare"],
  ["Pharmacy & laboratory","/pharmacy-lab","⚕","Dispensing and laboratory operations","Healthcare"],
  ["Payroll & HR","/payroll","◷","People, payroll and statutory administration","People"],
  ["SACCO & microfinance","/sacco","◈","Member services, savings and credit operations","Finance"],
 ]},
 {title:"Platform administration",items:[
  ["Platform control plane","/platform","⬡","Tenant lifecycle, plans and platform resources","Admin"],
  ["Integrations","/integrations","⌘","Provider connectivity and configuration status","Admin"],
  ["Audit & operations","/operations","◉","Audit trails, service health and operations","Admin"],
  ["Analytics & reports","/analytics","▥","Business intelligence and reporting workspace","Insights"],
  ["Settings","/settings","⚙","Workspace preferences and API configuration","Admin"],
 ]}
];
export const allModules = groups.flatMap(g=>g.items);
export const legacyRoutes = new Set(["/accounting","/pos","/inventory","/procurement","/crm","/crm/automation","/crm/forecast","/school","/school/advanced","/healthcare/hospital","/healthcare","/pharmacy-lab"]);
export const descriptions = {
 "/accounting":["Financial control centre","Review journals, invoices, budgets, fiscal periods and statements.","/api/v1/accounting"],
 "/pos":["Sales and checkout","Open the point-of-sale workspace for checkout, shifts, returns and cash controls.","/api/v1/pos"],
 "/inventory":["Stock and warehouse control","Track catalogue, stock movement, reservations and availability.","/api/v1/inventory"],
 "/procurement":["Purchasing and supplier workflows","Manage requisitions, RFQs, purchase orders, receipts and supplier invoices.","/api/v1/procurement"],
 "/crm":["Customer and sales management","Manage contacts, leads, sales activity, quotes and customer relationships.","/api/v1/crm"],
 "/crm/automation":["Campaign delivery and automation","Build audiences, prepare campaigns and monitor communication delivery.","/api/v1/crm/campaigns"],
 "/crm/forecast":["Sales pipeline intelligence","Explore forecasting and sales performance tools.","/api/v1/crm/analytics"],
 "/school":["School administration","Access learner, class, attendance and assessment management.","/api/v1/school"],
 "/school/advanced":["Advanced school workflows","Access advanced academic and school administration workflows.","/api/v1/school"],
 "/healthcare/hospital":["Hospital operations","Access hospital operations and clinical workflow tools.","/api/v1/healthcare"],
 "/healthcare":["Healthcare privacy and patient access","Review privacy, consent, patient access and audit controls.","/api/v1/healthcare"],
 "/pharmacy-lab":["Pharmacy and laboratory","Access dispensing, inventory and laboratory workflow tools.","/api/v1/pharmacy-lab"]
};
