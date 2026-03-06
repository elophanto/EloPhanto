export interface Package {
  slug: string;
  name: string;
  tagline: string;
  price: string;
  priceNote: string;
  duration: string;
  heroImage: string;
  description: string;
  includes: string[];
  whatToExpect: string[];
  itinerary?: { day: string; details: string }[];
  requirements: string[];
  testimonial: {
    quote: string;
    author: string;
    location: string;
  };
  seo: {
    title: string;
    description: string;
    keywords: string[];
  };
}

export const packages: Package[] = [
  {
    slug: "discovery",
    name: "Polo Discovery Experience",
    tagline: "Your first steps into the world of polo",
    price: "€199",
    priceNote: "per person",
    duration: "2 hours",
    heroImage:
      "https://images.unsplash.com/photo-1565128939020-0f18a5c0960e?w=1920&q=80",
    description:
      "The perfect introduction to polo for complete beginners. In just two hours, you'll learn the basics, ride a polo pony, and play your very first chukker — all capped off with a champagne toast under the Andalusian sun.",
    includes: [
      "Polo introduction and history (15 min)",
      "Horse riding basics for beginners (15 min)",
      "Stickwork practice on wooden horse (15 min)",
      "One chukker with instructor guidance (45 min)",
      "Champagne toast celebration",
      "Digital photo package (20 edited photos)",
      "All equipment provided (helmets, boots, mallets)",
    ],
    whatToExpect: [
      "No prior horse riding experience needed",
      "Wear comfortable clothes — we provide helmets and boots",
      "Group size: 4–6 people",
      "Available daily at 10:00 AM, 2:00 PM, and 6:00 PM",
      "Suitable for ages 12 and above",
    ],
    requirements: [
      "Minimum age: 12 years",
      "No prior experience needed",
      "Comfortable clothing recommended",
      "Closed-toe shoes (riding boots provided)",
    ],
    testimonial: {
      quote:
        "I had never been near a horse before, and within two hours I was galloping across the field with a mallet in my hand. The champagne toast afterwards was the cherry on top. Absolutely unforgettable!",
      author: "Emma Richardson",
      location: "London, UK",
    },
    seo: {
      title:
        "Polo Discovery Experience in Sotogrande | Beginner Polo | €199",
      description:
        "Try polo for the first time in Sotogrande, Spain. Our 2-hour discovery experience includes instruction, gameplay, champagne toast, and photos. No experience needed. Book now for €199.",
      keywords: [
        "polo experience sotogrande",
        "try polo spain",
        "beginner polo",
        "polo for beginners",
        "polo discovery",
      ],
    },
  },
  {
    slug: "weekend",
    name: "Polo Weekend Package",
    tagline: "An immersive two-day polo adventure",
    price: "€599",
    priceNote: "per person",
    duration: "2 days",
    heroImage:
      "https://images.unsplash.com/photo-1558618666-fcd25c85f82e?w=1920&q=80",
    description:
      "Spend a weekend immersed in the sport of kings. Over two days you'll progress from basics to competitive gameplay, enjoy gourmet lunches at the club, and leave with a branded polo shirt and certificate of participation.",
    includes: [
      "Day 1: Full Polo Discovery Experience",
      "Day 2: Two competitive chukkers (2 hours)",
      "All equipment (helmets, boots, mallets)",
      "Gourmet lunch at club restaurant (both days)",
      "Digital photo package (50 edited photos)",
      "Branded polo shirt (your size)",
      "Certificate of participation",
    ],
    whatToExpect: [
      "Prior horse riding helpful but not required",
      "Comfortable clothes — all equipment provided",
      "Group size: 4–6 people",
      "Saturday 10 AM – 6 PM, Sunday 10 AM – 4 PM",
      "Accommodation add-ons available from €200/night",
    ],
    itinerary: [
      {
        day: "Saturday",
        details:
          "Morning: Polo Discovery session with basics & stickwork. Lunch at club restaurant. Afternoon: First chukker with instructor guidance.",
      },
      {
        day: "Sunday",
        details:
          "Morning: Advanced skills & strategy. Two competitive chukkers. Lunch and certificate ceremony. Depart by 4 PM.",
      },
    ],
    requirements: [
      "Minimum age: 14 years",
      "No prior experience required",
      "Moderate fitness level recommended",
      "Comfortable clothing",
    ],
    testimonial: {
      quote:
        "My wife and I booked the weekend package for our anniversary. By Sunday we were playing competitive chukkers against each other. The lunches were superb, and the whole experience felt incredibly premium for the price.",
      author: "Marcus & Sophie Jansen",
      location: "Amsterdam, Netherlands",
    },
    seo: {
      title:
        "Polo Weekend Package in Sotogrande | 2-Day Experience | €599",
      description:
        "Immersive 2-day polo weekend in Sotogrande, Spain. Includes lessons, gameplay, gourmet lunches, photos, and polo shirt. From €599 per person. Book your polo weekend break.",
      keywords: [
        "polo weekend spain",
        "polo lessons sotogrande",
        "polo holiday packages",
        "weekend polo break",
        "polo weekend package",
      ],
    },
  },
  {
    slug: "week-immersion",
    name: "Polo Week Immersion",
    tagline: "The ultimate polo vacation in Andalusia",
    price: "€1,499",
    priceNote: "per person (accommodation included)",
    duration: "5 days, 4 nights",
    heroImage:
      "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=1920&q=80",
    description:
      "A transformative five-day polo immersion in Sotogrande. Daily lessons, evening social events, match-watching during tournament season, and a final tournament with prizes. Accommodation, meals, and all activities included.",
    includes: [
      "Daily polo lessons (3 chukkers/day, 2 hours)",
      "4-star hotel accommodation (private room)",
      "Daily breakfast and lunch",
      "Evening social events (welcome drinks, tapas night, farewell dinner)",
      "Match-watching during tournament season (Jul–Aug)",
      "Daily video analysis and personal feedback",
      "Final tournament with prizes",
      "Certificate of completion",
      "Branded polo shirt and cap",
      "Premium photo + video package (100+ photos, 10-min highlight video)",
    ],
    whatToExpect: [
      "No prior horse riding experience needed",
      "Intensive but supportive program",
      "Group size: 4–8 people",
      "Schedule: 10 AM – 4 PM daily (plus evening events)",
      "5-star upgrade available (+€400)",
    ],
    itinerary: [
      {
        day: "Monday",
        details:
          "Arrival and check-in. Welcome drinks at the club. Polo Discovery introduction session.",
      },
      {
        day: "Tuesday",
        details:
          "Three chukkers with progressive skills. Video analysis session. Evening tapas night.",
      },
      {
        day: "Wednesday",
        details:
          "Three chukkers with team strategy. Match-watching (tournament season). Free evening.",
      },
      {
        day: "Thursday",
        details:
          "Three chukkers with tournament preparation. Strategy session. Free evening to explore Sotogrande.",
      },
      {
        day: "Friday",
        details:
          "Final tournament with prizes. Prize ceremony and farewell lunch. Departure.",
      },
    ],
    requirements: [
      "Minimum age: 16 years",
      "No prior experience needed",
      "Good general fitness recommended",
      "Pack comfortable clothing and swimwear",
    ],
    testimonial: {
      quote:
        "Five days that changed my life. I arrived knowing nothing about polo and left feeling like I'd found my new passion. The instructors were world-class, the hotel was beautiful, and the farewell tournament was the highlight of my year.",
      author: "Henrik Larsson",
      location: "Stockholm, Sweden",
    },
    seo: {
      title:
        "Polo Week Immersion in Sotogrande | 5-Day Luxury Package | €1,499",
      description:
        "5-day luxury polo holiday in Sotogrande, Spain. Includes accommodation, daily lessons, meals, social events, and final tournament. All-inclusive from €1,499. Book your polo vacation.",
      keywords: [
        "polo holidays spain",
        "luxury equestrian tourism",
        "polo vacation spain",
        "equestrian holidays andalucia",
        "polo week package",
      ],
    },
  },
  {
    slug: "corporate",
    name: "Corporate Team Building",
    tagline: "Unforgettable team experiences on the polo field",
    price: "€2,500",
    priceNote: "per group (6–12 people)",
    duration: "Half-day (4 hours)",
    heroImage:
      "https://images.unsplash.com/photo-1552664730-d307ca884978?w=1920&q=80",
    description:
      "Give your team an experience they'll never forget. Our corporate polo events combine team building, competition, and luxury hospitality — all on the beautiful polo fields of Sotogrande. Perfect for company retreats, client entertainment, or celebrating milestones.",
    includes: [
      "Polo introduction for the whole team (30 min)",
      "Mini-tournament with teams of 3 (3 chukkers)",
      "All equipment and horses",
      "Professional instructor for each team",
      "Gourmet catering: lunch and drinks",
      "Team awards ceremony",
      "Video highlights (10-minute montage)",
      "Digital photo package (50+ photos)",
    ],
    whatToExpect: [
      "No prior horse riding experience needed",
      "Focus on team collaboration and fun",
      "Suitable for all fitness levels",
      "Professional photos and video for company marketing",
      "Full-day option available (+€1,500)",
    ],
    itinerary: [
      {
        day: "Morning Session",
        details:
          "Arrival and welcome. Polo introduction and safety briefing. Basic skills training in teams.",
      },
      {
        day: "Tournament",
        details:
          "Mini-tournament with 3 chukkers. Teams of 3 compete with instructor support. Live commentary.",
      },
      {
        day: "Celebration",
        details:
          "Gourmet lunch and drinks. Awards ceremony with trophies. Group photos and video highlights.",
      },
    ],
    requirements: [
      "Minimum group size: 6 people",
      "Maximum group size: 12 (larger groups available, +€1,000)",
      "50% deposit to secure booking",
      "Custom branding available (+€200)",
    ],
    testimonial: {
      quote:
        "We brought our leadership team of 10 for a half-day event. The combination of challenge, teamwork, and luxury was perfect. Three months later, people are still talking about it. Best corporate event we've ever organized.",
      author: "David Chen, VP Operations",
      location: "Deutsche Bank, Frankfurt",
    },
    seo: {
      title:
        "Corporate Polo Team Building in Spain | Unique Events | €2,500",
      description:
        "Unique corporate team building in Sotogrande, Spain. Polo-based events for 6–12 people. Includes catering, photos, video highlights. From €2,500 per group. Book a bespoke event.",
      keywords: [
        "corporate team building spain",
        "corporate polo events",
        "unique team building",
        "company retreat spain",
        "corporate events sotogrande",
      ],
    },
  },
  {
    slug: "lessons",
    name: "Private Polo Lessons",
    tagline: "One-on-one instruction at your pace",
    price: "€150",
    priceNote: "per hour",
    duration: "1 hour",
    heroImage:
      "https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=1920&q=80",
    description:
      "Accelerate your polo skills with personalised one-on-one instruction. Whether you're a complete beginner or an experienced player looking to refine your technique, our private lessons are tailored to your goals and pace.",
    includes: [
      "Private 1-on-1 instruction",
      "Horse and all equipment provided",
      "Custom lesson plan for your level",
      "Progress tracking across sessions",
      "Video feedback (optional, +€30)",
    ],
    whatToExpect: [
      "Suitable for all levels: beginner to advanced",
      "Customised instruction at your pace",
      "Flexible scheduling: morning, afternoon, or evening",
      "Free cancellation with 24 hours notice",
      "Package discounts available",
    ],
    requirements: [
      "Minimum age: 12 years",
      "No prior experience needed",
      "24-hour cancellation policy for full refund",
      "Comfortable clothing and closed-toe shoes",
    ],
    testimonial: {
      quote:
        "After a Discovery session I was hooked. Ten private lessons later and I'm playing in local matches. The personalised coaching made all the difference — my instructor knew exactly how to push me without overwhelming me.",
      author: "James Whitfield",
      location: "Marbella, Spain",
    },
    seo: {
      title:
        "Private Polo Lessons in Sotogrande | 1-on-1 Coaching | €150/hour",
      description:
        "Private polo lessons in Sotogrande, Spain. Personalised 1-on-1 instruction for all levels. Horse and equipment included. €150/hour with package discounts available.",
      keywords: [
        "polo lessons sotogrande",
        "private polo coach",
        "polo instructor spain",
        "learn polo fast",
        "private polo lessons",
      ],
    },
  },
];

export const testimonials = [
  {
    quote:
      "The polo discovery was the highlight of our trip to Spain. Professional, fun, and incredibly well-organised. We felt like royalty!",
    author: "Sarah & Tom Mitchell",
    location: "Manchester, UK",
    rating: 5,
  },
  {
    quote:
      "I've done team building events all over Europe. Nothing comes close to the polo experience in Sotogrande. My team is still buzzing about it months later.",
    author: "Anna Krüger, HR Director",
    location: "Siemens, Munich",
    rating: 5,
  },
  {
    quote:
      "The week immersion programme was life-changing. Five days of incredible instruction, beautiful surroundings, and genuine hospitality. I've already booked my return trip.",
    author: "Pierre Dubois",
    location: "Paris, France",
    rating: 5,
  },
  {
    quote:
      "Transparent pricing, no hidden costs, and a genuinely premium experience. This is how tourism should be done.",
    author: "Ingrid Haugen",
    location: "Oslo, Norway",
    rating: 5,
  },
  {
    quote:
      "Booked the weekend package as a birthday gift for my husband. He says it's the best present he's ever received. The champagne toast with the Andalusian sunset was pure magic.",
    author: "Lisa Van den Berg",
    location: "Brussels, Belgium",
    rating: 5,
  },
  {
    quote:
      "As someone who was terrified of horses, I can't believe I played polo within two hours. The instructors were patient, professional, and made me feel completely safe.",
    author: "Yuki Tanaka",
    location: "Tokyo, Japan",
    rating: 5,
  },
];

export const faqs = [
  {
    question: "Do I need any horse riding experience?",
    answer:
      "Not at all! All our experiences are designed to be accessible to complete beginners. Our professional instructors will teach you everything you need to know, from basic horse handling to hitting the ball. Many of our guests have never been on a horse before.",
  },
  {
    question: "What should I wear?",
    answer:
      "Wear comfortable clothes that allow free movement — think jeans or trousers and a fitted top. We provide all specialist equipment including helmets, riding boots, and mallets. Avoid loose scarves or dangling jewellery for safety.",
  },
  {
    question: "Is polo safe for beginners?",
    answer:
      "Absolutely. Safety is our highest priority. All sessions are supervised by certified instructors, and we use calm, well-trained polo ponies accustomed to beginners. Full safety equipment (helmets, boots) is provided and mandatory.",
  },
  {
    question: "What is your cancellation policy?",
    answer:
      "Full refund for cancellations made 48+ hours before your booking. 50% refund for 24–48 hours notice. Unfortunately we cannot offer refunds for cancellations with less than 24 hours notice. We recommend travel insurance for international visitors.",
  },
  {
    question: "What ages are suitable?",
    answer:
      "The Discovery Experience is suitable for ages 12+. The Weekend Package is for ages 14+. The Week Immersion is for ages 16+. Private lessons are available from age 12. Children must be accompanied by an adult.",
  },
  {
    question: "Can you help arrange accommodation?",
    answer:
      "Yes! We partner with hotels in Sotogrande ranging from 3-star to 5-star luxury. Accommodation add-ons are available for all packages. The Week Immersion includes 4-star accommodation as standard.",
  },
  {
    question: "When is the best time to visit?",
    answer:
      "Sotogrande enjoys year-round sunshine. The polo tournament season runs July–August (peak season). May–June and September offer great weather with fewer crowds. We operate year-round with seasonal pricing.",
  },
  {
    question: "How do I get to Sotogrande?",
    answer:
      "The nearest airports are Gibraltar (GIB, 20 min drive) and Málaga (AGP, 90 min drive). We can arrange airport transfers on request. Sotogrande is also easily accessible by car from the Costa del Sol.",
  },
];
