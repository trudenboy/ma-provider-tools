// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import react from '@astrojs/react';

// https://astro.build/config
export default defineConfig({
	site: 'https://trudenboy.github.io',
	base: '/ma-provider-tools',
	integrations: [
		react(),
		starlight({
			title: 'MA Provider Tools',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/trudenboy/ma-provider-tools' },
			],
			editLink: {
				baseUrl: 'https://github.com/trudenboy/ma-provider-tools/edit/main/',
			},
			customCss: ['./src/styles/custom.css'],
			sidebar: [
				{ label: 'Dashboard', slug: 'dashboard' },
				{
					label: 'Docs',
					items: [
						{ label: 'Workflow Overview', slug: 'workflow-overview' },
						{ label: 'Adding a Provider', slug: 'adding-provider' },
						{ label: 'GitHub Projects Setup', slug: 'github-projects-setup' },
					],
				},
			],
		}),
	],
});
