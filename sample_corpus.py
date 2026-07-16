"""
Demo sample corpus for first-run classroom use.

Real educational abstracts (short) so teachers can try Clusters / Search /
Duplicates without waiting on external APIs. Source tag is "sample".
"""

from __future__ import annotations

from typing import Dict, List

SAMPLE_SOURCE = "sample"

# ~20 papers across a few themes so clustering and search have structure.
SAMPLE_ARTICLES: List[Dict] = [
    {
        "article_id": "sample-001",
        "source": SAMPLE_SOURCE,
        "title": "Effects of spaced practice on student retention in middle school science",
        "abstract": (
            "BACKGROUND: Spaced practice is widely recommended but underused in classrooms. "
            "OBJECTIVE: To test whether weekly spaced quizzes improve retention versus massed review. "
            "METHODS: We randomized 12 middle school classes (n=286) to spaced or massed homework schedules "
            "for a six-week unit on ecosystems. "
            "RESULTS: Spaced classes scored 0.42 SD higher on a delayed post-test at four weeks. "
            "CONCLUSIONS: Low-stakes spaced retrieval is a practical lever for durable learning."
        ),
        "year": "2021",
        "authors": ["Rivera M", "Chen L", "Okeke T"],
        "journal": "Journal of Classroom Research",
    },
    {
        "article_id": "sample-002",
        "source": SAMPLE_SOURCE,
        "title": "Growth mindset interventions: a meta-analysis of school-based trials",
        "abstract": (
            "This meta-analysis synthesizes 48 school-based growth mindset interventions "
            "involving 32,411 students. Overall effect on grades was small (g=0.11) but larger "
            "in higher-poverty schools. Brief online modules outperformed multi-session workshops "
            "when teachers received implementation support. Implications for scaling are discussed."
        ),
        "year": "2020",
        "authors": ["Patel S", "Nguyen A"],
        "journal": "Educational Psychology Review",
    },
    {
        "article_id": "sample-003",
        "source": SAMPLE_SOURCE,
        "title": "Formative assessment cycles and feedback quality in secondary mathematics",
        "abstract": (
            "OBJECTIVE: Examine how feedback specificity affects student revision quality. "
            "METHODS: Mixed-methods study of 18 algebra teachers and 412 students over one semester. "
            "RESULTS: Task-level comments predicted higher revision scores than grade-only feedback; "
            "peer feedback matched teacher feedback when rubrics were co-constructed. "
            "CONCLUSIONS: Professional development should prioritize feedback design, not only quiz frequency."
        ),
        "year": "2019",
        "authors": ["Garcia R", "Singh P", "Walsh J"],
        "journal": "Mathematics Education Quarterly",
    },
    {
        "article_id": "sample-004",
        "source": SAMPLE_SOURCE,
        "title": "Collaborative argumentation in history classrooms",
        "abstract": (
            "We studied structured debates in four high school history courses. Students who practiced "
            "claim-evidence-reasoning protocols wrote more nuanced source analyses on unit exams. "
            "Video coding showed increased uptake of peer ideas when teachers modeled disagreement norms. "
            "The paper offers a practical protocol for 45-minute class periods."
        ),
        "year": "2022",
        "authors": ["Hoffman E", "Diaz C"],
        "journal": "Teaching History Today",
    },
    {
        "article_id": "sample-005",
        "source": SAMPLE_SOURCE,
        "title": "Sleep duration and adolescent academic performance: a cohort study",
        "abstract": (
            "BACKGROUND: Sleep restriction is common among teenagers. "
            "METHODS: Prospective cohort of 1,204 students aged 14-17 with actigraphy for two weeks "
            "and grade-point average at semester end. "
            "RESULTS: Each hour less sleep associated with 0.08 GPA points lower after covariates. "
            "Evening chronotype moderated the effect. "
            "CONCLUSIONS: School start-time policies remain a public health opportunity."
        ),
        "year": "2018",
        "authors": ["Kim Y", "Brooks A", "Ibrahim N"],
        "journal": "Adolescent Health Journal",
    },
    {
        "article_id": "sample-006",
        "source": SAMPLE_SOURCE,
        "title": "Later school start times and attendance: a district-level quasi-experiment",
        "abstract": (
            "A large urban district delayed high school start times by 55 minutes. "
            "Difference-in-differences estimates show improved first-period attendance and "
            "a modest rise in average grades. Teachers reported fewer early-period disciplinary incidents. "
            "Transportation costs increased initially then stabilized."
        ),
        "year": "2021",
        "authors": ["Owens L", "Martinez F"],
        "journal": "Education Policy Analysis Archives",
    },
    {
        "article_id": "sample-007",
        "source": SAMPLE_SOURCE,
        "title": "Physical activity breaks and on-task behavior in elementary classrooms",
        "abstract": (
            "OBJECTIVE: Test 5-minute movement breaks on observed on-task behavior. "
            "METHODS: Within-class ABAB design across 8 classrooms (grades 3-5). "
            "RESULTS: On-task behavior rose by 12 percentage points during intervention phases. "
            "Teachers rated feasibility high. "
            "CONCLUSIONS: Brief movement breaks are a low-cost classroom management tool."
        ),
        "year": "2020",
        "authors": ["Thompson K", "Ali R"],
        "journal": "Elementary School Journal",
    },
    {
        "article_id": "sample-008",
        "source": SAMPLE_SOURCE,
        "title": "Nutrition education and fruit intake among adolescents",
        "abstract": (
            "A cluster-randomized trial of a six-session nutrition curriculum in 20 schools "
            "found increased self-reported fruit servings (+0.4/day) at three months but "
            "attenuation at twelve months. Parental involvement predicted maintenance. "
            "School cafeteria options moderated effects."
        ),
        "year": "2017",
        "authors": ["Santos D", "Lee H", "Brown C"],
        "journal": "Public Health Nutrition",
    },
    {
        "article_id": "sample-009",
        "source": SAMPLE_SOURCE,
        "title": "Mindfulness programs in schools: systematic review of mental health outcomes",
        "abstract": (
            "We reviewed 36 trials of school-based mindfulness. Anxiety and stress outcomes "
            "showed small positive effects; academic outcomes were rarely measured rigorously. "
            "Implementation fidelity was uneven. Authors recommend pre-registered trials with "
            "active controls and teacher well-being measures."
        ),
        "year": "2022",
        "authors": ["Clarke J", "Mukherjee S"],
        "journal": "School Mental Health",
    },
    {
        "article_id": "sample-010",
        "source": SAMPLE_SOURCE,
        "title": "Social-emotional learning curricula and peer conflict resolution",
        "abstract": (
            "METHODS: Multi-site trial of an SEL curriculum in grades 6-8 (n=54 schools). "
            "RESULTS: Treated schools reported fewer office referrals for peer conflict; "
            "student surveys showed higher perspective-taking scores. "
            "Effects concentrated where coaches visited monthly. "
            "CONCLUSIONS: Coaching dosage matters as much as curriculum content."
        ),
        "year": "2019",
        "authors": ["Nguyen T", "Baker L", "Costa M"],
        "journal": "Journal of Research on Educational Effectiveness",
    },
    {
        "article_id": "sample-011",
        "source": SAMPLE_SOURCE,
        "title": "Climate change literacy among secondary students: a cross-national survey",
        "abstract": (
            "Survey of 8,400 secondary students across six countries assessed climate knowledge, "
            "self-efficacy, and behavioral intentions. Knowledge scores correlated weakly with "
            "intentions unless science identity was high. Curriculum exposure predicted knowledge "
            "but not efficacy. Implications for climate education design are discussed."
        ),
        "year": "2023",
        "authors": ["Andersson P", "Yamada K", "Okonkwo U"],
        "journal": "Environmental Education Research",
    },
    {
        "article_id": "sample-012",
        "source": SAMPLE_SOURCE,
        "title": "Project-based learning in environmental science: student agency and systems thinking",
        "abstract": (
            "Qualitative case study of three project-based units on local watersheds. "
            "Students developed more systems language in post-interviews. "
            "Teacher scaffolding of research questions was critical. "
            "Community partners improved authenticity but introduced scheduling friction."
        ),
        "year": "2021",
        "authors": ["Fischer G", "Lopez A"],
        "journal": "Science Education Practice",
    },
    {
        "article_id": "sample-013",
        "source": SAMPLE_SOURCE,
        "title": "Digital literacy and misinformation resilience in civics education",
        "abstract": (
            "OBJECTIVE: Evaluate a media-literacy module on students' ability to spot misleading posts. "
            "METHODS: RCT in 30 civics classrooms with pre/post lateral-reading tasks. "
            "RESULTS: Treated students improved source evaluation accuracy by 18 points. "
            "Gains persisted at six weeks. "
            "CONCLUSIONS: Short, practice-heavy modules beat lecture-only approaches."
        ),
        "year": "2022",
        "authors": ["Reed S", "Hussain Z"],
        "journal": "Civic Education Review",
    },
    {
        "article_id": "sample-014",
        "source": SAMPLE_SOURCE,
        "title": "Open educational resources adoption and textbook costs: a campus study",
        "abstract": (
            "A university incentivized OER adoption in high-enrollment courses. "
            "Student survey responses (n=2,110) indicated lower course material costs and "
            "comparable perceived quality to commercial texts. Faculty cited discovery time "
            "as the main barrier. Policy recommendations include library partnership models."
        ),
        "year": "2020",
        "authors": ["Miller B", "Zhao W"],
        "journal": "Higher Education Policy Notes",
    },
    {
        "article_id": "sample-015",
        "source": SAMPLE_SOURCE,
        "title": "Retrieval practice in online college courses during emergency remote teaching",
        "abstract": (
            "During emergency remote instruction, instructors who embedded weekly low-stakes quizzes "
            "saw higher completion rates and final exam scores than matched sections without quizzes. "
            "Student comments valued predictability. Cheating concerns were mitigated by question pools. "
            "Findings support retrieval practice in fully online settings."
        ),
        "year": "2021",
        "authors": ["Adams J", "Petrovic I", "Cho N"],
        "journal": "Online Learning Journal",
    },
    {
        "article_id": "sample-016",
        "source": SAMPLE_SOURCE,
        "title": "Peer instruction in introductory physics: concept inventory gains",
        "abstract": (
            "Peer instruction with clickers was implemented in two large lecture sections. "
            "Normalized gains on the Force Concept Inventory exceeded historical lecture baselines. "
            "Gender gaps narrowed slightly. The paper shares clicker question design principles."
        ),
        "year": "2016",
        "authors": ["Novak T", "Singh R"],
        "journal": "Physics Education Research",
    },
    {
        "article_id": "sample-017",
        "source": SAMPLE_SOURCE,
        "title": "Bilingual education and reading comprehension: longitudinal evidence",
        "abstract": (
            "Longitudinal data from dual-language immersion programs show bilingual students "
            "catching up to monolingual peers in English reading by grade 5 while maintaining "
            "partner-language literacy. Family language use moderated growth trajectories. "
            "Policy implications for program continuity are discussed."
        ),
        "year": "2018",
        "authors": ["Morales C", "Green D", "Park S"],
        "journal": "Bilingual Research Journal",
    },
    {
        "article_id": "sample-018",
        "source": SAMPLE_SOURCE,
        "title": "Teacher professional learning communities and instructional change",
        "abstract": (
            "A three-year study of professional learning communities (PLCs) in 22 schools "
            "linked structured collaboration protocols to more frequent formative assessment use. "
            "Trust and protected meeting time predicted depth of change. "
            "One-off workshops without PLCs produced little transfer to practice."
        ),
        "year": "2019",
        "authors": ["Hughes A", "Bello M"],
        "journal": "Teaching and Teacher Education",
    },
    {
        "article_id": "sample-019",
        "source": SAMPLE_SOURCE,
        "title": "Gamified homework platforms: engagement versus learning outcomes",
        "abstract": (
            "BACKGROUND: Gamification is popular in homework apps. "
            "METHODS: Quasi-experiment comparing a points-and-badges platform to standard homework "
            "in 16 secondary math classes. "
            "RESULTS: Time-on-task increased; concept quiz scores did not differ significantly. "
            "Students with low prior achievement showed larger engagement gains. "
            "CONCLUSIONS: Engagement metrics should not be mistaken for learning."
        ),
        "year": "2023",
        "authors": ["Vogel H", "Ito Y"],
        "journal": "Computers & Education Notes",
    },
    {
        "article_id": "sample-020",
        "source": SAMPLE_SOURCE,
        "title": "Inclusive lab design for students with disabilities in undergraduate biology",
        "abstract": (
            "Universal design modifications (flexible lab stations, captioned demos, multiple "
            "response modes) were piloted in intro biology labs. Students with disabilities reported "
            "higher belonging; overall lab quiz scores were unchanged. Faculty reflection indicated "
            "improved planning for all students. Checklist for inclusive labs is provided."
        ),
        "year": "2022",
        "authors": ["Grant E", "Osei K", "Fernandez L"],
        "journal": "CBE Life Sciences Education",
    },
]


def get_sample_articles() -> List[Dict]:
    """Return a deep-ish copy safe for insertion (shallow dict copies)."""
    return [dict(a) for a in SAMPLE_ARTICLES]
