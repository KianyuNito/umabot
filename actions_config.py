# the 5 shoes you can request from the club (Sprint, Mile, Medium, Long, Dirt Race)
CLUB_ITEMS = ("sprint", "mile", "medium", "long", "dirt")


SEED_ACTIONS = [
    {
        "name": "daily_runs",
        "order_idx": 3,
        "enabled": 1,
        # settings = what the USER of the app can change
        "settings": {
            "races_at_once": 6,        # races to set in the Multi-Race window each time (1-6)
            "race": "moonlight_sho",   # uses templates <race>_btn and <race>_difficulty
        },
        # info = the database entry describing HOW the action works on screen
        "info": {
            "description": "Daily runs",
            "options": {"race": ["moonlight_sho", "jupiter_cup"], "races_at_once": [1, 2, 3, 4, 5, 6]},
            # reach the Daily Programs screen (shows the Daily Races card with its counter)
            "navigate": [
                # starts from the Home screen: tap the Race tab
                {"type": "tap", "template": "home_race_btn", "timeout": 5},
                {"type": "expect_screen", "screen": "race", "timeout": 10},
                # the Daily Program card on the Race page says "Done for today!" once the daily races AND the legend
                # race are both finished: then there is nothing to do, so finish here without opening Daily Programs.
                # (needs `daily_program_done_marker`: a crop of that "Done for today!" strip; the action fails without it)
                {"type": "finish_if_visible", "template": "daily_program_done_marker", "wait": 2,
                 "detail": "Race page shows 'Done for today!' on Daily Program (daily races and legend race both complete)"},
                {"type": "tap", "template": "daily_program_btn", "timeout": 10},
            ],
            # Daily Programs screen -> Daily Races list (Moonlight Sho / Jupiter Cup)
            "enter": [
                {"type": "tap", "template": "daily_race_btn", "timeout": 10},
            ],
            # if this is visible after navigating, the action is already complete
            "done_marker": "daily_done_marker",
            "run_steps": [
                {"type": "tap", "template": "{race}_btn", "timeout": 10},
                {"type": "tap", "template": "{race}_difficulty", "timeout": 10},
                {"type": "tap", "template": "race_btn", "timeout": 10},
                {"type": "tap", "template": "confirm_btn", "timeout": 10},
                # Multi-Race window: must be on screen. Press minus 5 times (always ends at 1), then plus
                # (races_at_once - 1) times. Fails loudly if the window or a button isn't found.
                {"type": "expect_screen", "screen": "multi_race", "timeout": 10},
                {"type": "tap_times", "template": "multi_race_minus_btn", "times": 5, "timeout": 5, "after": 0.4},
                {"type": "tap_times", "template": "multi_race_plus_btn", "times_setting": "races_at_once",
                 "minus": 1, "timeout": 5, "after": 0.4},
                {"type": "tap", "template": "race_start_btn", "timeout": 15},
                {"type": "wait", "template": "race_result_screen", "timeout": 90},
                # closing the results returns to the runner selection screen
                {"type": "tap", "template": "race_close_btn", "timeout": 15},
                # the Daily Sale pop-up can appear after this race -> Cancel it (skipped if it doesn't show);
                # the watch keeps looking for it if it turns up late, until we are back home
                {"type": "popup_watch", "on": True},
                {"type": "tap", "template": "daily_sale_cancel_btn", "timeout": 8, "optional": True},
            ],
            # race list -> home screen via the Home tab in the bottom bar;
            # "navigate" then runs again to reach the Daily Programs screen for the done check
            "back": [
                # Home tab at the bottom: if its picture isn't found, tap its usual spot instead
                {"type": "tap", "template": "home_btn", "timeout": 5, "fallback_xy": [553, 1010]},
                {"type": "expect_screen", "screen": "home", "timeout": 10},
                {"type": "popup_watch", "on": False},
            ],
            "exit": [
                # the Back button (bottom-left) instead of the Home tab: the Home tab's colour differs per page,
                # so its picture often isn't matched
                {"type": "tap", "template": "back_btn", "timeout": 10, "optional": True},
            ],
        },
    },
    {
        "name": "daily_legend_race",
        "order_idx": 2,
        "enabled": 1,
        "settings": {
            # which legend to challenge: uses template legend_<name>.png
            # (capture another legend's tile as legend_<other_name> and type that name here)
            "legend": "tokai_teio",
            # items on the "Items Selected" dialog before the race (at most MAX_ITEMS can be ticked)
            "mood_boost": False, "weather_sunny": False, "weather_rain": False,
            "inner_bracket": False, "outer_bracket": False,
        },
        "info": {
            "description": "Daily Legend Race",
            "dynamic_options": {"legend": "available_legends"},   # dropdown built from captured tiles
            # home -> Race tab -> Daily Program (the screen that shows the Legend card + its counter)
            "navigate": [
                # starts from the Home screen: tap the Race tab
                {"type": "tap", "template": "home_race_btn", "timeout": 5},
                {"type": "expect_screen", "screen": "race", "timeout": 10},
                # the Daily Program card on the Race page says "Done for today!" once the daily races AND the legend
                # race are both finished: then there is nothing to do, so finish here without opening Daily Programs.
                # (needs `daily_program_done_marker`: a crop of that "Done for today!" strip; the action fails without it)
                {"type": "finish_if_visible", "template": "daily_program_done_marker", "wait": 2,
                 "detail": "Race page shows 'Done for today!' on Daily Program (daily races and legend race both complete)"},
                {"type": "tap", "template": "daily_program_btn", "timeout": 10},
            ],
            # checked on the Daily Programs screen, before and after the race
            "done_marker": "legend_done_marker",
            "enter": [
                {"type": "tap", "template": "daily_legend_btn", "timeout": 10},
            ],
            "run_steps": [
                # list of legends -> pick one (first make sure the list is on screen)
                {"type": "expect_screen", "screen": "legend_list", "timeout": 10},
                {"type": "tap", "template": "legend_{legend}", "timeout": 4, "after": 1.5,
                 # tile not visible? drag the list up (scroll down) and look again
                 "scroll": {"x": 553, "from_y": 780, "to_y": 500, "tries": 8}},
                # every legend's race list shows the race with an "EX" badge: tap that one badge template
                # (same for all legends, no per-legend race tile needed), then Race + Confirm
                # the race list slides in, and a tap during that animation doesn't register: wait for the badge,
                # let the screen settle, then tap it (the tap re-finds the badge, so it hits where it ended up)
                {"type": "wait", "template": "legend_race_ex", "timeout": 10},
                {"type": "sleep", "seconds": 0.7},
                {"type": "tap", "template": "legend_race_ex", "timeout": 10, "after": 1.2},
                {"type": "tap", "template": "race_btn", "timeout": 10},
                {"type": "tap", "template": "confirm_btn", "timeout": 10},
                # runners list: wait for its green Next button (the same on every race, whoever the runners
                # are), instead of a picture of the list, which changes with the race, the umas and their moods
                {"type": "wait", "template": "legend_next_btn", "timeout": 30},
                {"type": "tap", "template": "legend_next_btn", "timeout": 10},
                # "Items Selected" dialog: tap each chosen item (only for the items that are ticked)
                {"type": "expect_screen", "screen": "legend_items", "timeout": 10},
                {"type": "tap", "template": "legend_item_mood_boost", "timeout": 6, "after": 0.6, "only_if": "mood_boost"},
                {"type": "tap", "template": "legend_item_weather_sunny", "timeout": 6, "after": 0.6, "only_if": "weather_sunny"},
                {"type": "tap", "template": "legend_item_weather_rain", "timeout": 6, "after": 0.6, "only_if": "weather_rain"},
                {"type": "tap", "template": "legend_item_inner_bracket", "timeout": 6, "after": 0.6, "only_if": "inner_bracket"},
                {"type": "tap", "template": "legend_item_outer_bracket", "timeout": 6, "after": 0.6, "only_if": "outer_bracket"},
                # then Race! (consumes 1 ticket)
                {"type": "tap", "template": "legend_items_race_btn", "timeout": 10},
                # detail screen -> View Results
                {"type": "tap", "template": "legend_view_results_btn", "timeout": 30},
                # wait for the placing banner, then tap anywhere on the game area
                {"type": "wait", "template": "legend_result_1st", "timeout": 90},
                {"type": "sleep", "seconds": 1.5},
                {"type": "tap_xy", "x": 553, "y": 540, "after": 1.5},
                # Next (win screen), then Next again (rewards screen)
                {"type": "tap", "template": "legend_next_btn", "timeout": 20, "after": 2.0},
                {"type": "tap", "template": "legend_next_btn", "timeout": 20, "after": 2.0},
                # Daily Sale pop-up can appear after a legend race too -> Cancel it if it shows
                {"type": "popup_watch", "on": True},
                {"type": "tap", "template": "daily_sale_cancel_btn", "timeout": 10, "after": 2.0, "optional": True},
            ],
            # Home tab in the bottom bar, then "navigate" is repeated for the done check
            "back": [
                # the Home tab as it looks when NOT selected (dark "Home" word), with its usual spot as a fallback
                {"type": "tap", "template": "home_btn_unselected", "timeout": 10, "fallback_xy": [553, 1010]},
                {"type": "expect_screen", "screen": "home", "timeout": 10},
                {"type": "popup_watch", "on": False},
            ],
            "exit": [
                {"type": "tap", "template": "home_btn_unselected", "timeout": 10, "fallback_xy": [553, 1010]},
            ],
        },
    },
    {
        "name": "independent_run",
        "order_idx": 4,
        "enabled": 0,                  # off by default: it spends 30 TP, so the user opts in
        "settings": {
            # which saved agenda ("My Agendas" list) to load; uses template agenda_<name>.png
            "agenda": "maxverstap",
            # finished run: spend the leftover skill points on skills (Complete Career screen -> Skills) before
            # completing the career
            "learn_skills": False,
        },
        "info": {
            "description": "Independent career",
            "dynamic_options": {"agenda": "available_agendas"},
            "phase_titles": {"run_steps": "Step"},
            "run_steps": [
                # --- home -> Career -> scenario / trainee / legacy ---------------------------------
                # --- a finished Independent Training run is waiting (home Career card shows "Post-Career"):
                #     collect the results and complete the career first, then carry on to the new run ----------
                {"type": "if_visible", "template": "ind_done_home_career_btn", "wait": 3, "skip_if_missing": True,
                 "label": "finished run found: collect the results and complete the career",
                 "steps": [
                     {"type": "tap", "template": "ind_done_home_career_btn", "timeout": 5, "after": 1.5},
                     # "Independent Training - TRAINING COMPLETE!" dialog -> Career
                     {"type": "tap", "template": "ind_done_career_btn", "timeout": 10, "after": 2.0},
                     # Training Log: Overview page -> arrow to the Career page, scroll down to the items, then OK
                     {"type": "tap", "template": "ind_done_log_arrow_btn", "timeout": 10, "after": 1.5},
                     # scrolls by pulling the list's scroll bar (right edge, x~836) to the bottom, so no item icon
                     # (shoes etc.) is ever pressed. If no scroll bar is found it drags the list instead, starting
                     # on a race card's text (x=470, y=715), away from the item icons.
                     {"type": "scroll_bottom", "region": [200, 780],
                      "scroll": {"bar_x": 836, "x": 470, "from_y": 715, "to_y": 230, "tries": 40,
                                 "duration": 0.25, "settle": 0.5}},
                     # record the carats (rainbow carrot) earned this run; no carrot in the list = 0
                     {"type": "record_carats", "template": "ind_done_carat_icon"},
                     {"type": "tap", "template": "ind_done_log_ok_btn", "timeout": 10, "after": 2.0},
                     # optional (setting "learn_skills"): Complete Career screen -> Skills -> pick every skill the skill
                     # points can still pay for (top to bottom, scrolling) -> Confirm -> Learn -> Close -> Back.
                     # Confirm / Learn / Close are optional taps: with nothing picked Confirm is greyed out, so the
                     # bot just moves on to Back.
                     {"type": "if_visible", "template": "ind_skills_btn", "wait": 3, "skip_if_missing": True,
                      "only_if": "learn_skills",
                      "label": "learn skills with the leftover skill points (only when ticked)",
                      "steps": [
                          {"type": "read_aptitudes", "only_if": "learn_skills"},
                          {"type": "tap", "template": "ind_skills_btn", "timeout": 8, "after": 2.0},
                          {"type": "expect_screen", "screen": "ind_skill_learn", "timeout": 10},
                          {"type": "plan_skills", "label": "plan and buy the best skills for the points"},
                          {"type": "tap", "template": "ind_skill_confirm_btn", "timeout": 4, "optional": True, "after": 1.5},
                          {"type": "tap", "template": "ind_skill_learn_btn", "timeout": 5, "optional": True, "after": 2.5},
                          {"type": "tap", "template": "ind_skill_close_btn", "timeout": 8, "optional": True, "after": 1.5},
                          {"type": "tap", "template": "ind_skill_back_btn", "timeout": 10, "after": 2.0},
                      ]},
                     # Complete Career -> Finish
                     {"type": "tap", "template": "ind_done_complete_career_btn", "timeout": 10, "after": 1.5},
                     {"type": "tap", "template": "ind_done_finish_btn", "timeout": 10, "after": 2.5},
                     # Career Rank -> Next
                     {"type": "tap", "template": "ind_done_next_btn", "timeout": 15, "after": 2.5},
                     # Sparks -> Confirm, then "Keep this set of Sparks?" -> Confirm
                     {"type": "tap", "template": "ind_done_sparks_confirm_btn", "timeout": 15, "after": 1.5},
                     {"type": "tap", "template": "ind_done_sparks_keep_btn", "timeout": 10, "after": 2.5},
                     # Umamusume Details -> Close
                     {"type": "tap", "template": "ind_done_details_close_btn", "timeout": 15, "after": 1.5},
                     # Epithet -> Confirm! (only when the dialog shows up)
                     {"type": "tap", "template": "ind_done_epithet_confirm_btn", "timeout": 4, "optional": True, "after": 2.0},
                     # Career record, Rewards, Support Cards -> Next each time
                     {"type": "tap", "template": "ind_done_next_btn", "timeout": 10, "after": 2.5},
                     {"type": "tap", "template": "ind_done_next_btn", "timeout": 10, "after": 2.5},
                     {"type": "tap", "template": "ind_done_next_btn", "timeout": 10, "after": 2.5},
                     # ongoing event only: "Rewards Collected" popup -> Close, then the event points page -> Next,
                     # then "Event Reward" -> Next. Checked first, since there is no event at some times.
                     {"type": "tap_xy", "x": 553, "y": 540},
                     {"type": "if_visible", "template": "ind_done_event_collected_popup", "wait": 6,
                      "label": "event rewards: Close the popup, then Next twice (only when an event is running)",
                      "steps": [
                          # make sure this really is the "Rewards Collected" popup before any clicking
                          {"type": "expect_screen", "screen": "ind_event_rewards", "timeout": 5},
                          {"type": "tap", "template": "ind_done_event_close_btn", "timeout": 5, "after": 2.0},
                          {"type": "tap", "template": "ind_done_next_btn", "timeout": 10, "after": 2.5},
                          {"type": "tap", "template": "ind_done_next_btn", "timeout": 10, "after": 2.5},
                      ]},
                     # Career Complete -> Close
                     {"type": "tap", "template": "ind_done_next_btn", "timeout": 6, "optional": True, "after": 2.5},
                     {"type": "tap", "template": "ind_done_complete_close_btn", "timeout": 10, "after": 1.5},
                 ]},
                {"type": "tap", "template": "home_career_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "ind_scenario", "timeout": 10},
                {"type": "tap", "template": "career_next_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "ind_trainee", "timeout": 10},
                {"type": "tap", "template": "career_next_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "ind_legacy", "timeout": 10},
                {"type": "tap", "template": "career_next_btn", "timeout": 10, "after": 1.5},
                # --- support formation: fill the empty Friends slot (skipped if it is already filled) ---
                {"type": "expect_screen", "screen": "ind_support", "timeout": 10},
                {"type": "if_visible", "template": "ind_friend_slot", "steps": [
                    {"type": "tap", "template": "ind_friend_slot", "timeout": 5, "after": 1.5},
                    {"type": "expect_screen", "screen": "ind_borrow", "timeout": 10},
                    # Borrow Card list: scroll (up and down) until the wanted friend card is found, then tap it
                    {"type": "tap", "template": "ind_friend_card", "timeout": 4, "after": 1.5,
                     "scroll": {"x": 553, "from_y": 820, "to_y": 420, "tries": 10}},
                ]},
                {"type": "tap", "template": "ind_start_career_btn", "timeout": 10, "after": 1.5},
                # --- Final Confirmation: Independent Training tab, then load the agenda ---------------
                {"type": "expect_screen", "screen": "ind_final", "timeout": 10},
                # tab already selected (green)? then do nothing; otherwise tap it
                {"type": "if_visible", "template": "ind_tab_independent_selected", "negate": True, "wait": 3,
                 "label": "select the Independent Training tab (only if not already selected)",
                 "steps": [
                     {"type": "tap", "template": "ind_tab_independent", "timeout": 10, "after": 1.0},
                 ]},
                {"type": "tap", "template": "ind_agenda_edit_btn", "timeout": 10, "after": 1.2},
                {"type": "tap", "template": "ind_my_agendas_btn", "timeout": 10, "after": 1.2},
                # find the agenda's name in the list (scrolls up/down if needed) and tap the Load List below it
                {"type": "tap_below", "anchor": "agenda_{agenda}", "template": "ind_load_list_btn", "timeout": 2,
                 "after": 1.2, "scroll": {"x": 553, "from_y": 800, "to_y": 520, "tries": 8}},
                {"type": "tap", "template": "ind_close_btn", "timeout": 10, "after": 1.2},
                # --- start ---------------------------------------------------------------------------
                {"type": "tap", "template": "ind_start_btn", "timeout": 10, "after": 1.5},
                # "Your trainee will start training independently" -> OK (not shown if "Do not show again" is on)
                {"type": "tap", "template": "ind_ok_btn", "timeout": 6, "optional": True, "after": 1.5},
                # --- "Training..." screen: menu button (bottom right) -> Menu -> To Home ---------------
                {"type": "expect_screen", "screen": "ind_training", "timeout": 10},
                {"type": "tap", "template": "ind_menu_btn", "timeout": 10, "after": 1.5},
                {"type": "tap", "template": "ind_to_home_btn", "timeout": 10, "delay": 0.5, "after": 2.0},
            ],
        },
    },
    {
        "name": "club_daily",
        "order_idx": 1,
        "enabled": 0,                  # off until its templates are captured; tick it when ready
        "settings": {
            # which shoe to ask the club for; uses template club_item_<item>_shoes.png
            "item": "sprint",
        },
        "info": {
            "description": "Club daily",
            "options": {"item": list(CLUB_ITEMS)},
            "phase_titles": {"run_steps": "Step"},
            "run_steps": [
                # --- home -> Club ---------------------------------------------------------------------
                {"type": "tap", "template": "home_club_btn", "timeout": 10, "after": 2.0},
                # --- a finished/expired request shows a result popup when you enter the club screen -> Close it.
                #     It covers the club screen, so this comes BEFORE the Club marker check.
                #     If there is no popup, carry straight on. ---------------------------------------------
                {"type": "if_visible", "template": "club_request_result_popup", "wait": 6,
                 "label": "close the finished item-request popup (only if it appears)",
                 "steps": [
                     {"type": "tap", "template": "club_request_result_close_btn", "timeout": 5, "after": 1.2},
                 ]},
                {"type": "expect_screen", "screen": "club", "timeout": 10},
                # --- ask for the chosen shoes: the Item Request list is already open on this screen.
                #     Tapping a shoe opens a "Confirm Request" dialog. With the 8-hour cooldown the dialog shows
                #     a red "You must wait 8 hours..." line -> Cancel. Without it -> Confirm (never both). ----
                {"type": "tap", "template": "club_item_{item}_shoes", "timeout": 6, "optional": True, "after": 1.0},
                {"type": "if_visible", "template": "club_request_cooldown_msg", "wait": 2,
                 "label": "8-hour cooldown: Cancel, otherwise Confirm the request",
                 "steps": [
                     {"type": "tap", "template": "club_request_cancel_btn", "timeout": 5, "after": 1.2},
                 ],
                 "else_steps": [
                     {"type": "tap", "template": "club_request_confirm_btn", "timeout": 4, "optional": True, "after": 1.5},
                 ]},
                # --- donate to everyone (skipped if the donation button isn't on screen) ----------------
                {"type": "if_visible", "template": "club_donations_btn", "wait": 3,
                 "label": "donate to all (only if the donation button is on screen)",
                 "steps": [
                     {"type": "tap", "template": "club_donations_btn", "timeout": 5, "after": 1.2},
                     # nothing to donate to (no requests in the list) -> no Donate to All / confirm to tap,
                     # so both are optional and the run simply moves on to Close
                     {"type": "tap", "template": "club_donate_all_btn", "timeout": 4, "optional": True, "after": 1.2},
                     {"type": "tap", "template": "club_donate_confirm_btn", "timeout": 2, "optional": True, "after": 1.5},
                 ]},
                # --- close the list and go back home ----------------------------------------------------
                {"type": "tap", "template": "club_close_btn", "timeout": 6, "optional": True, "after": 1.2},
                {"type": "tap", "template": "home_btn", "timeout": 6},
            ],
        },
    },
    {
        "name": "daily_missions",
        "order_idx": 7,                # last: the other actions are what complete the missions
        "enabled": 0,                  # off until its templates are captured; tick it when ready
        "settings": {},
        "info": {
            "description": "Collect daily mission rewards",
            "phase_titles": {"run_steps": "Step"},
            "run_steps": [
                # --- home -> Missions (the clipboard icon on the right side of the home screen) ----------
                {"type": "tap", "template": "home_missions_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "mission", "timeout": 10},
                # --- Daily tab is the one that opens first; Collect All only collects what is finished.
                #     When nothing is left to collect the button is greyed out, so it isn't found -> moves on ----
                {"type": "tap", "template": "missions_collect_all_btn", "timeout": 5, "optional": True, "after": 2.0},
                # --- the rewards popup that can appear after collecting -> Close (only if it shows up) --------
                {"type": "tap", "template": "missions_reward_close_btn", "timeout": 4, "optional": True, "after": 1.5},
                # --- back to the home screen ------------------------------------------------------------------
                {"type": "tap", "template": "home_btn", "timeout": 6},
            ],
        },
    },
    {
        "name": "daily_shop",
        "order_idx": 6,                # before the daily missions (in case one counts a shop purchase)
        "enabled": 0,                  # off until its templates are captured; tick it when ready
        # What to buy is chosen on the Settings page (info "settings_page" lists those keys; the main page hides them).
        # A ticked item buys EVERY row of that kind in the Daily Sales. Star Pieces stay on, as before.
        "settings": {"buy_star_piece": True, "buy_clock": False, "buy_parfait": False, "buy_shoe": False,
                     "buy_support_points": False, "buy_sash": False},
        "info": {
            "description": "Daily shop (what to buy: see Settings)",
            "settings_page": ["buy_star_piece", "buy_clock", "buy_parfait", "buy_shoe",
                              "buy_support_points", "buy_sash"],
            "phase_titles": {"run_steps": "Step", "exit": "Go home"},
            "run_steps": [
                # --- home -> Shop (cart icon, bottom left; crop it WITHOUT the red "Daily" badge) --------
                {"type": "tap", "template": "home_shop_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "shop", "timeout": 10},
                # --- Shop menu -> Daily Sales ---------------------------------------------------------------
                {"type": "tap", "template": "shop_daily_sales_btn", "timeout": 10, "after": 1.5},
                {"type": "sleep", "seconds": 1.5},     # let the Daily Sales list load before ticking rows
                # --- tick EVERY row whose name ends in "Star Piece" (alarm clocks etc. are left alone): go to the
                #     top of the list, tick the Star Pieces on screen, scroll down, repeat until the list stops
                #     moving (= the bottom), so Star Pieces further down are ticked too. No Star Piece found =
                #     already bought today, so the action finishes as done. -------------------------------------
                # anchors: setting name -> picture of the words every row of that kind shares. The first one
                # (Star Pieces) sits at the top of the list; only the ones ticked in Settings are looked for.
                {"type": "tick_rows", "checkbox": "shop_checkbox_empty",
                 "anchors": {"buy_star_piece": "shop_star_piece_text",
                             "buy_clock": "shop_alarm_clock_text",
                             "buy_parfait": "shop_parfait_text",
                             "buy_shoe": "shop_shoe_text",
                             "buy_support_points": "shop_support_points_text",
                             "buy_sash": "shop_sash_text"},
                 "dy": [-25, 80], "region": [440, 775], "after": 0.6, "stop_gap": 130,
                 "scroll": {"x": 553, "from_y": 720, "to_y": 520, "tries": 30},
                 "detail": "nothing left to buy in the Daily Sales (already bought)"},
                # --- Confirm -> "Confirm Exchange" dialog -> Exchange -> "Exchange Complete" -> Close ----------
                {"type": "tap", "template": "shop_confirm_btn", "timeout": 8, "after": 1.5},
                {"type": "tap", "template": "shop_exchange_btn", "timeout": 8, "after": 2.0},
                {"type": "tap", "template": "shop_complete_close_btn", "timeout": 10, "after": 1.5},
            ],
            # the Home tab at the bottom (its picture differs per page, so tap its usual spot if not matched)
            "exit": [
                {"type": "tap", "template": "home_btn_unselected", "timeout": 5, "fallback_xy": [553, 1010]},
                {"type": "expect_screen", "screen": "home", "timeout": 10},
            ],
        },
    },
    {
        "name": "team_trials",
        "order_idx": 5,                # before the daily missions, which may count a Team Trials race
        "enabled": 0,                  # off until its templates are captured; tick it when ready
        "settings": {"opponent": "weak",       # weak = bottom card, medium = middle, strong = top
                     "races": 1,               # how many races to do (1-5)
                     # items on the "Items Selected" dialog before each race (at most MAX_ITEMS can be ticked)
                     "mood_boost": False, "weather_sunny": False, "weather_rain": False,
                     "inner_bracket": False, "outer_bracket": False},
        "info": {
            "description": "Team Trials",
            "options": {"opponent": ["weak", "medium", "strong"], "races": [1, 2, 3, 4, 5]},
            "repeat_from": 6,                  # extra races start at step 7 (Select Opponent): Race Again brings us back there
            "phase_titles": {"run_steps": "Step"},
            "run_steps": [
                # --- Home -> Race tab, then the Team Trials card ------------------------------------------------
                {"type": "tap", "template": "home_race_btn", "timeout": 5},
                {"type": "expect_screen", "screen": "race", "timeout": 10},
                {"type": "tap", "template": "team_trials_btn", "timeout": 10, "after": 1.5},
                # --- Team Trials page -> Team Race -------------------------------------------------------------
                {"type": "expect_screen", "screen": "team_page", "timeout": 10},
                {"type": "tap", "template": "team_race_btn", "timeout": 10, "after": 1.5},
                {"type": "expect_screen", "screen": "team_opponent", "timeout": 10},
                # --- Select Opponent: the cards are listed strongest first, so weak = the BOTTOM card, medium =
                #     the middle one, strong = the TOP one. Fixed spots: the opponents change every time, so
                #     there is no picture to look for. ---------------------------------------------------------
                {"type": "sleep", "seconds": 1.0},     # let the opponent list finish loading before tapping a card
                {"type": "tap_xy", "x": 553, "y": 738, "after": 1.5,
                 "y_by": {"setting": "opponent", "values": {"strong": 282, "medium": 510, "weak": 738}}},
                # --- opponent / team overview -> Next ------------------------------------------------------------
                {"type": "tap", "template": "team_next_btn", "timeout": 10, "after": 1.5},
                # --- "Items Selected" dialog: tap each chosen item (only the ticked ones; same item pictures as the
                #     Daily Legend Race), then Race! (costs 1 RP) -------------------------------------------------
                {"type": "expect_screen", "screen": "team_items", "timeout": 10},
                {"type": "tap", "template": "legend_item_mood_boost", "timeout": 6, "after": 0.6, "only_if": "mood_boost"},
                {"type": "tap", "template": "legend_item_weather_sunny", "timeout": 6, "after": 0.6, "only_if": "weather_sunny"},
                {"type": "tap", "template": "legend_item_weather_rain", "timeout": 6, "after": 0.6, "only_if": "weather_rain"},
                {"type": "tap", "template": "legend_item_inner_bracket", "timeout": 6, "after": 0.6, "only_if": "inner_bracket"},
                {"type": "tap", "template": "legend_item_outer_bracket", "timeout": 6, "after": 0.6, "only_if": "outer_bracket"},
                {"type": "tap", "template": "team_race_confirm_btn", "timeout": 10, "after": 2.0},
                # --- race screen: the green button at the bottom starts the races ------------------------------
                {"type": "tap", "template": "team_see_result_btn", "timeout": 10, "after": 1.5},
                # --- races play: tap the fast-forward button (skips ahead) or just wait for RACE FINISHED -----
                {"type": "tap", "template": "team_skip_btn", "timeout": 8, "optional": True, "after": 1.0,
                 "delay": 0.25},                  # click 0.15s sooner than the usual 0.4s after the button is spotted
                {"type": "wait", "template": "team_race_finished", "timeout": 180},
                {"type": "tap", "template": "team_finished_next_btn", "timeout": 10, "after": 2.5},
                {"type": "tap_xy", "x": 553, "y": 540, "after": 1.0},
                {"type": "tap_xy", "x": 553, "y": 540, "after": 1.0},
                # one tap anywhere on the game before the WINNINGS check
                # --- "NEW HIGH SCORE!" banner: shows after Next, only after a new best; tap anywhere to close it ---
                {"type": "if_visible", "template": "team_high_score_banner", "wait": 3,
                 "label": "NEW HIGH SCORE banner: tap to close it (only if it appears)",
                 "steps": [
                     {"type": "sleep", "seconds": 1.5},     # the banner is still animating in: a tap now is ignored
                     {"type": "tap_xy", "x": 553, "y": 540, "after": 1.5},
                 ]},
                # --- the Daily Sale popup can show here -> Cancel (skipped if it doesn't) ------------------------
                {"type": "popup_watch", "on": True, "steps": [
                    {"type": "tap", "template": "daily_sale_cancel_btn", "timeout": 3, "optional": True},
                ]},
                {"type": "if_visible", "template": "team_race_again_btn", "negate": True, "wait": 2,
                 "label": "tap Next only if Race Again is not on screen",
                 "steps": [
                     {"type": "tap", "template": "team_win_next_btn", "timeout": 15, "after": 2.0, "optional": True},
                 ]},
                {"type": "if_visible", "template": "team_winnings_header", "wait": 3,
                 "label": "WINNINGS popup: record the carats, then Next (only if it appears)",
                 "steps": [
                     # "crop" = the area, relative to the carat picture's centre, that holds the "x300" count.
                     # Check records\carats_*.png after a run and nudge these numbers if the crop misses it.
                     {"type": "record_carats", "template": "team_carat_icon", "crop": [0, 28, 74, 56],
                      "label": "Team Trials"},
                     {"type": "tap", "template": "team_winnings_next_btn", "timeout": 10, "after": 2.0},
                 ]},
                {"type": "tap", "template": "team_race_again_btn", "timeout": 15, "after": 2.0, "only_if": "more_races"},
                {"type": "tap", "template": "team_result_next_btn", "timeout": 15, "after": 2.0, "unless": "more_races"},
                # --- WINNINGS popup (comes after the result page's Next; only when a gift box was won): note the carats, then Next --
                # --- back to the home screen via the (unselected) Home tab ---------------------------------------
                {"type": "tap", "template": "home_btn_unselected", "timeout": 10, "fallback_xy": [553, 1010], "unless": "more_races"},
            ],
        },
    },
]