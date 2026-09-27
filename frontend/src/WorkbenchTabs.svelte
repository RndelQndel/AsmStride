<script lang="ts">
  let { label, tabs, selected = $bindable(), children }: {
    label: string;
    tabs: string[];
    selected: string;
    children?: import('svelte').Snippet;
  } = $props();

  function navigate(event: KeyboardEvent, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    selected = tabs[next];
    (event.currentTarget as HTMLButtonElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next].focus();
  }
</script>

<div class="tab-bar" role="tablist" aria-label={label}>
  {#each tabs as tab, index}
    <button role="tab" aria-selected={selected === tab} tabindex={selected === tab ? 0 : -1} onclick={() => selected = tab} onkeydown={(event) => navigate(event, index)}>{tab}</button>
  {/each}
  {@render children?.()}
</div>
