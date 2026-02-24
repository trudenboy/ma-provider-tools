import type { SidebarsConfig } from "@docusaurus/plugin-content-docs";

const sidebars: SidebarsConfig = {
  docs: [
    "index",
    "dashboard",
    {
      type: "category",
      label: "Docs",
      items: ["workflow-overview", "adding-provider", "github-projects-setup"],
    },
  ],
};

export default sidebars;
