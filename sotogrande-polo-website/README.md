# Sotogrande Polo Tourism Website

Production-ready marketing website for Sotogrande Polo Tourism — a luxury equestrian tourism business in Sotogrande, Andalusia, Spain.

## Tech Stack

- **Framework:** Next.js 16 with App Router
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4
- **Fonts:** Inter (sans) + Playfair Display (serif) via next/font
- **Deployment:** Optimized for Vercel

## Pages

| Route | Page |
|---|---|
| `/` | Homepage — hero, packages overview, testimonials, location |
| `/packages` | All packages with comparison table |
| `/packages/discovery` | Polo Discovery Experience — €199 |
| `/packages/weekend` | Polo Weekend Package — €599 |
| `/packages/week-immersion` | Polo Week Immersion — €1,499 |
| `/packages/corporate` | Corporate Team Building — €2,500 |
| `/packages/lessons` | Private Polo Lessons — €150/hr |
| `/about` | About us, partnership model, partners, team |
| `/contact` | Contact form, FAQ, location info |

## Getting Started

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Start production server
npm start
```

Open [http://localhost:3000](http://localhost:3000) to see the site.

## Project Structure

```
src/
├── app/
│   ├── layout.tsx          # Root layout with Header, Footer, SEO, JSON-LD
│   ├── page.tsx            # Homepage
│   ├── globals.css         # Tailwind CSS + custom theme
│   ├── about/page.tsx      # About page
│   ├── contact/page.tsx    # Contact page
│   └── packages/
│       ├── page.tsx        # All packages overview
│       └── [slug]/page.tsx # Individual package detail (SSG)
├── components/
│   ├── Header.tsx          # Sticky navigation with mobile menu
│   ├── Footer.tsx          # Site footer with links and contact
│   ├── PackageCard.tsx     # Package preview card
│   ├── TestimonialCard.tsx # Guest review card
│   ├── ContactForm.tsx     # Booking inquiry form
│   └── FAQ.tsx             # Accordion FAQ component
└── lib/
    └── data.ts             # All package data, testimonials, FAQs
```

## SEO

- Meta tags (title, description, OG, Twitter) on every page
- JSON-LD structured data for LocalBusiness + SportsActivityLocation
- Semantic HTML (h1, h2, etc.)
- Alt text on all images
- Clean URL structure
- Static generation for optimal performance

## Deploy to Vercel

1. Push this repository to GitHub
2. Import the project at [vercel.com/new](https://vercel.com/new)
3. Select the `sotogrande-polo-website` directory as root
4. Deploy — no environment variables needed

## Next Phase

- Supabase database for booking storage
- Stripe payment integration
- Email automation (confirmation, reminders)
- Blog section for SEO content marketing
- Google Maps embed on contact page
