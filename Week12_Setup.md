# Week 12 Setup - Final Review, Refinement & Submission
**Goal:** Incorporate feedback, fix bugs, finalize code cleanup, ensure README, requirements, Dockerfile, and submit final repo, report, slides, video.

## Prerequisites
- Completed Week 11 setup (documentation, presentation prep)
- Python virtual environment activated (`source venv/Scripts/activate` or `source RAATS_Test.venv/Scripts/activate`)
- Required packages installed: yfinance, pandas-ta, matplotlib, seaborn, backtrader (install as needed)
- Basic understanding of code cleanup and verification

## Daily Activities with Runnable Code Snippets

### Monday 19 Oct – Final Report Writing
1. Ensure you are in the RAATS_Test project root:
   ```bash
   cd /c/Users/Zamuxolo/RAATS_Test
   ```
2. Activate virtual environment (if not already):
   ```bash
   source venv/Scripts/activate
   ```
3. Complete the final project report by filling in all sections:
   - Abstract
   - Introduction
   - Literature Review
   - Methodology
   - System Design and Architecture
   - Implementation
   - Results and Evaluation
   - Conclusion and Future Work
   - References
4. Use the weekly reflections and deliverables as source material.
5. Commit progress:
   ```bash
   git add reports/RAATS_Final_Report.md
   git commit -m "Complete final project report"
   git push origin dev
   ```

### Tuesday 20 Oct – Slide Deck Finalization
1. Refine the slide deck based on the completed report.
2. Ensure slides are visually appealing, concise, and professional.
3. Export to PDF or PowerPoint format if required.
4. Commit the slide deck:
   ```bash
   git add presentation/RAATS_Slides.md
   git commit -m "Finalize slide deck"
   git push origin dev
   ```

### Wednesday 21 Oct – Demo Video Recording and Editing
1. Record the demo video following the script from Week 11.
2. Key points to demonstrate:
   - System architecture overview
   - Agent analyzing market data and generating trading signals
   - Risk management validation
   - Simulated trade execution
   - Performance tracking and metrics
   - Backtesting results comparison
3. Edit the video to ensure it is under 5 minutes.
4. Save the video in an appropriate format (e.g., MP4).
5. Add the video to the repository (or provide a link if too large).
   ```bash
   mkdir -p presentation/videos
   # Assume the video file is named RAATS_Demo.mp4 and is in the current directory
   mv RAATS_Demo.mp4 presentation/videos/
   ```
6. Commit the video (if small enough) or note its location.
   ```bash
   # If the video is small enough to commit:
   git add presentation/videos/RAATS_Demo.mp4
   git commit -m "Add demo video"
   git push origin dev
   ```
   If the video is too large, we can skip adding it to git and just note the location in the commit message.

### Thursday 22 Oct – Code Cleanup and Verification
1. Perform final code cleanup:
   - Remove debug comments and print statements.
   - Ensure consistent code formatting (we can use a formatter like black or autopep8).
   - Verify that all modules and scripts are importable and runnable.
2. Create a verification script to check the repository health:
   ```python
   # File: scripts/verify_repo.py
   import os
   import sys

   def check_file_exists(filepath):
       if not os.path.exists(filepath):
           print(f"ERROR: Missing file: {filepath}")
           return False
       print(f"OK: {filepath}")
       return True

   def check_directory_exists(dirpath):
       if not os.path.isdir(dirpath):
           print(f"ERROR: Missing directory: {dirpath}")
           return False
       print(f"OK: {dirpath}")
       return True

   if __name__ == "__main__":
       checks = [
           ("README.md", check_file_exists),
           ("requirements.txt", check_file_exists),
           ("src/agent/state.py", check_file_exists),
           ("src/agent/trading_loop.py", check_file_exists),
           ("deployment/docker-compose.yml", check_file_exists),
           ("deployment/agent/Dockerfile", check_file_exists),
           ("reports/RAATS_Final_Report.md", check_file_exists),
           ("presentation/RAATS_Slides.md", check_file_exists),
           ("presentation/videos/RAATS_Demo.mp4", check_file_exists),  # May fail if video not added
           ("logs", check_directory_exists),
           ("notebooks", check_directory_exists),
           ("journal", check_directory_exists),
       ]

       all_passed = True
       for item, check_func in checks:
           if not check_func(item):
               all_passed = False

       if all_passed:
           print("\nAll checks passed!")
           sys.exit(0)
       else:
           print("\nSome checks failed!")
           sys.exit(1)
   ```
3. Run the verification script and fix any issues.
4. Commit the verification script and any cleanup changes:
   ```bash
   git add scripts/verify_repo.py
   # Add any other changed files from cleanup
   git commit -m "Add verification script and final code cleanup"
   git push origin dev
   ```

### Friday 23 Oct – Morning: Final Verification and Preparation
1. Run the verification script one last time.
2. Ensure all weekly reflections are committed.
3. Create a final summary document (optional).
4. Afternoon: Rest (no work).

### Saturday 24 Oct – Rest day
- No planned project work.

### Sunday 25 Oct – Final Submission
1. Double-check that all required deliverables are present:
   - Final project report (reports/RAATS_Final_Report.md)
   - Slide deck (presentation/RAATS_Slides.md)
   - Demo video (presentation/videos/RAATS_Demo.mp4)
   - Clean and well-documented code repository
   - README.md with instructions
   - requirements.txt
   - Dockerfiles and docker-compose.yml
2. Optionally, create a release or tag the final commit.
3. The week ends with the submission of the final project.

---\n**End of Week 12 Deliverables:**\n- Report: reports/RAATS_Final_Report.md\n- Presentation: presentation/RAATS_Slides.md, presentation/videos/RAATS_Demo.mp4\n- Verification: scripts/verify_repo.py\n- Logs: journal/week12_reflection.md (to be created after week)\n- Clean repository with all required files\n