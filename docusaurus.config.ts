import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const config: Config = {
  title: "MA Provider Tools",
  tagline: "Central infrastructure for Music Assistant custom providers",
  favicon: undefined,

  url: "https://trudenboy.github.io",
  baseUrl: "/ma-provider-tools/",

  organizationName: "trudenboy",
  projectName: "ma-provider-tools",

  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/",
          sidebarPath: "./sidebars.ts",
          editUrl:
            "https://github.com/trudenboy/ma-provider-tools/edit/main/",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    navbar: {
      title: "MA Provider Tools",
      items: [
        { to: "/", label: "Home", position: "left" },
        { to: "/dashboard", label: "Dashboard", position: "left" },
        {
          type: "dropdown",
          label: "Docs",
          position: "left",
          items: [
            { label: "Workflow Overview", to: "/workflow-overview" },
            { label: "Adding a Provider", to: "/adding-provider" },
            { label: "GitHub Projects Setup", to: "/github-projects-setup" },
          ],
        },
        {
          href: "https://github.com/trudenboy/ma-provider-tools",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Providers",
          items: [
            {
              label: "Yandex Music",
              href: "https://github.com/trudenboy/ma-provider-yandex-music",
            },
            {
              label: "KION Music",
              href: "https://github.com/trudenboy/ma-provider-kion-music",
            },
            {
              label: "Zvuk Music",
              href: "https://github.com/trudenboy/ma-provider-zvuk-music",
            },
            {
              label: "MSX Bridge",
              href: "https://github.com/trudenboy/ma-provider-msx-bridge",
            },
          ],
        },
        {
          title: "More",
          items: [
            {
              label: "GitHub",
              href: "https://github.com/trudenboy/ma-provider-tools",
            },
          ],
        },
      ],
      copyright: `Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ["yaml", "bash"],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
