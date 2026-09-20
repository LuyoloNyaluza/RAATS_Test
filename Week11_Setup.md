# Week 11 Setup - Documentation & Presentation Prep
**Goal:** Write project report, build slide deck, record 5‑min demo video.

## Prerequisites
- Completed Week 10 setup (evaluation framework, backtesting)
- Python virtual environment activated (`source venv/Scripts/activate` or `source RAATS_Test.venv/Scripts/activate`)
- Required packages installed: yfinance, pandas-ta, matplotlib, seaborn, backtrader (install as needed)
- Basic understanding of markdown and presentation tools

## Daily Activities with Runnable Code Snippets

### Monday 12 Oct – Project Report Writing
1. Ensure you are in the RAATS_Test project root:
   ```bash
   cd /c/Users/Zamuxolo/RAATS_Test
   ```
2. Activate virtual environment (if not already):
   ```bash
   source venv/Scripts/activate
   ```
3. Review all weekly reflections and deliverables to gather content for the report.
4. Create a structured outline for the final project report.
5. Start writing the introduction and methodology sections.
6. Create the file and commit:
   ```bash
   mkdir -p reports
   ```
   Then start drafting the report:
   ```bash
   cat > reports/RAATS_Final_Report.md << 'EOF'
   # Agentic AI System for Adaptive Real-Time Trading (RAATS)
   ## Final Project Report
   
   **Student:** Luyolo Nyaluza (MSc Computer Science, University of Fort Hare)
   **Email:** luyolon@hotmail.com
   **Date:** October 2026
   
   ## Abstract
   [To be completed]
   
   ## 1. Introduction
   [To be completed]
   
   ## 2. Literature Review
   [To be completed]
   
   ## 3. Methodology
   [To be completed]
   
   ## 4. System Design and Architecture
   [To be completed]
   
   ## 5. Implementation
   [To be completed]
   
   ## 6. Results and Evaluation
   [To be completed]
   
   ## 7. Conclusion and Future Work
   [To be completed]
   
   ## References
   [To be completed]
   EOF
   ```
   ```bash
   git add reports/RAATS_Final_Report.md
   git commit -m "Start final project report draft"
   git push origin dev
   ```

### Tuesday 13 Oct – Report Writing Continued
1. Continue writing the report, focusing on:
   - Literature review (LLMs for trading, agentic systems, LangGraph)
   - Methodology (data pipeline, agent design, risk management)
   - System architecture (components, data flow, technology stack)
2. Commit progress:
   ```bash
   git add reports/RAATS_Final_Report.md
   git commit -m "Add literature review and methodology sections"
   git push origin dev
   ```

### Wednesday 14 Oct – Slide Deck Creation
1. Create a presentation outline for the final demo.
2. Use a simple markdown-based slide tool or PowerPoint/LibreOffice.
3. Create initial slide deck:
   ```bash
   mkdir -p presentation
   ```
   Then create a basic slide structure:
   ```bash
   cat > presentation/RAATS_Slides.md << 'EOF'
   # RAATS: Agentic AI System for Adaptive Real-Time Trading
   
   ## Slide 1: Title Slide
   - Project Title: RAATS
   - Student: Luyolo Nyaluza
   - University: University of Fort Hare
   - Date: October 2026
   
   ## Slide 2: Project Overview
   - Goal: Develop an Agentic AI System for Adaptive Real-Time Trading
   - Duration: 12 weeks (Aug 3 - Oct 25, 2026)
   - Approach: LLM-guided strategy selection with Python execution
   
   ## Slide 3: System Architecture
   - Data Collector
   - Analyst (LLM with Ollama)
   - Risk Manager
   - Executor (Mock Trade)
   - Performance Logger
   
   ## Slide 4: Weekly Progress
   [Summary of weeks 1-10 accomplishments]
   
   ## Slide 5: Technical Implementation
   - Technologies: Python, LangGraph, Ollama, Docker, etc.
   - Key Components: Data pipeline, Agent graph, Risk management
   
   ## Slide 6: Results and Evaluation
   - Backtesting results
   - Performance metrics (Sharpe, max drawdown, etc.)
   - Comparison with baseline strategies
   
   ## Slide 7: Conclusion and Future Work
   - Summary of achievements
   - Limitations and future improvements
   
   ## Slide 8: Live Demo
   [To be demonstrated]
   
   ## Slide 9: Questions
   EOF
   ```
   ```bash
   git add presentation/RAATS_Slides.md
   git commit -m "Create initial slide deck outline"
   git push origin dev
   ```

### Thursday 15 Oct – Demo Video Preparation
1. Plan the 5-minute demo video script.
2. Identify key features to demonstrate:
   - Agent making trading decisions
   - Risk management in action
   - Paper trading simulation
   - Performance tracking
3. Create a demo script:
   ```bash
   cat > presentation/demo_script.md << 'EOF'
   # RAATS Demo Video Script (5 minutes)
   
   ## Introduction (30 seconds)
   - Welcome and project overview
   - Brief explanation of agentic AI for trading
   
   ## System Architecture (45 seconds)
   - Show diagram of components
   - Explain data flow: Collector → Analyst → Risk → Executor
   
   ## Live Demonstration (3 minutes)
   - Show the agent analyzing current market data
   - Display LLM analysis and trading signal
   - Demonstrate risk check validation
   - Show simulated trade execution
   - Display performance metrics updating
   
   ## Results Summary (45 seconds)
   - Show backtesting results from Week 10
   - Compare LLM-guided vs baseline strategies
   - Highlight key performance metrics
   
   ## Conclusion (30 seconds)
   - Summary of what was built
   - Potential future enhancements
   - Thank you and contact information
   EOF
   ```
   ```bash
   git add presentation/demo_script.md
   git commit -m "Create demo video script"
   git push origin dev
   ```

### Friday 16 Oct – Morning: Report and Slide Refinement
1. Continue writing the report, focusing on implementation and results sections.
2. Refine the slide deck based on report content.
3. Afternoon: Rest (no work).

### Saturday 17 Oct – Rest day
- No planned project work.

### Sunday 18 Oct – Preparation for Week 12
1. Review Week 12 plan: Final Review, Refinement & Submission.
2. Sketch a checklist for final code cleanup, documentation verification, and submission preparation.
3. Write a brief note in journal/week11_prep_week12.md.
4. Commit reflection for Week 11.
   ```markdown
   # Week 11 Reflection – Luyolo Nyaluza
   ## What went well
   - Started drafting the final project report with structured sections.
   - Created initial slide deck outline covering key project aspects.
   - Prepared demo video script highlighting system functionality.
   ## Challenges / Blockers
   - Balancing depth vs brevity in technical documentation.
   - Determining which implementation details to include in the report vs slides.
   ## Goals for Week 12
   - Complete the final project report with all sections.
   - Refine and finalize the slide deck.
   - Record the 5-minute demo video.
   - Perform final code cleanup and verification.
   - Prepare final submission package.
   ```
5. Commit reflection and prep note.
   ```bash
   mkdir -p journal
   cat > journal/week11_reflection.md << 'EOF'
   [content above]
   EOF
   ```
   ```bash
   cat > journal/week11_prep_week12.md << 'EOF'
   # Week 12 Preparation Notes
   ## Topic: Final Review, Refinement & Submission
   
   ## High-level architecture ideas:
   - Complete all remaining documentation (report, slides, video).
   - Perform final code cleanup: remove debug comments, ensure consistent formatting.
   - Verify all required files are present: README, requirements.txt, Dockerfiles, etc.
   - Create a final submission package with clear organization.
   
   ## Components to finalize:
   1. Final project report (complete with abstract, conclusion, references).
   2. Slide deck (visually appealing, concise, professional).
   3. Demo video (recorded, edited, under 5 minutes).
   4. Code repository (clean, well-documented, runnable).
   5. Submission checklist and package.
   
   ## Next steps:
   - Finish report writing.
   - Complete slide deck design.
   - Record and edit demo video.
   - Perform code cleanup.
   - Assemble final submission.
   EOF
   ```
   ```bash
   git add journal/week11_reflection.md journal/week11_prep_week12.md
   git commit -m "Add week 11 reflection and week 12 prep"
   git push origin dev
   ```

---\n**End of Week 11 Deliverables:**\n- Report: reports/RAATS_Final_Report.md (in progress)\n- Presentation: presentation/RAATS_Slides.md, presentation/demo_script.md\n- Logs: journal/week11_reflection.md\n- Preparation: journal/week11_prep_week12.md\n